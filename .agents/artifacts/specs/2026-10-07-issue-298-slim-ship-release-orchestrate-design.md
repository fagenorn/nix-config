# Slim ship-release and orchestrate-issues to skill best practices (#298)

Slice S7 of program [#291](https://github.com/fagenorn/nix-config/issues/291). The
program spec (`2026-10-07-issue-291-skill-best-practices-design.md`) binds this
slice, and its rows are cited as "#291 D<n>" without being restated. The slice-S4
spec (`2026-10-07-issue-295-slim-from-issue-design.md`) is the precedent, cited
as "#295 D<n>". This spec's own rows are D1–D18 in `## Decision ledger`.

## Problem

Every release owner and every orchestration dispatcher loads the whole of its
skill on every run. Most of that text is explanation an agent does not need in
order to act:

- `ship-release/SKILL.md` is 558 reflowed lines, over the L2 limit of 500. Its
  `CHANGELOG.md` is 224 lines with no `## Contents` (L3). Each of the two files
  loads hot in four profile-hosts (`release-owner` and `ship-release`, each on
  Claude and Codex), so each byte cut from them counts four times.
- `orchestrate-issues/SKILL.md` (Claude) is 510 lines, also over L2. It is the
  only member of `orchestration-dispatcher`.
- The Codex `orchestrate-issues` stub's description has no trigger clause (L5).
  None of the three descriptions is in the third person.
- Prose restates rules that the lifecycle guard, `workflow-state control` and
  `build-delivery` enforce, and those tools already explain their refusals.
  Examples are the merge grammar's release arm, slot admission, and the
  builder's resolution root.
- Rationale sits in the hot path: why the resume check comes first, why the CI
  wait is 300 s and stays in the foreground, why the tag is annotated, the
  silent-rollback story told three times, why orchestrate-issues is Claude-only.
- `test_workflow_skill_contracts.py` still pins prose sentences in these files
  (#291 D6). #316 already deleted most of them, and the remainder is listed
  below.

## Solution

**Cut in place, and add no files.** Each scoped document keeps its order and
its headings, except that ship-release loses `## The flow` (D7), the two `## Notes`
sections are folded into their homes or cut, and CHANGELOG gains `## Contents`. Within each section, the text is cut by content class (table below).
No route moves to a new reference file (D1), so `instruction-load.json` changes
only through `instruction_load tighten`. The slice needs no
`instruction-budget-raise` label and no human gate before merge (D2).

### Measured base (`75784bed`)

| File | Bytes | Reflowed lines | Profile-hosts loading it |
|---|---|---|---|
| `ship-release/SKILL.md` | 30,869 | 558 | 4 (hot) |
| `ship-release/CHANGELOG.md` | 11,060 | 224 | 4 (hot) |
| `orchestrate-issues/SKILL.md` (claude-only) | 29,389 | 510 | 1 (hot) |
| `orchestrate-issues/SKILL.md` (codex) | 1,035 | 21 | 0 (corpus only) |

Measured by section, `ship-release/SKILL.md` breaks down as:

- the Phase 5 deploy watch, 5,250 B;
- the Phase 4.5 tag and release steps, 5,900 B;
- Phase 0, 4,691 B;
- Phase 3, 2,366 B;
- Phase 4, 1,962 B;
- the six preface sections before Phase 0, 5,226 B;
- Phases 1, 2 and 6 plus Notes, 4,199 B.

Its fences hold 3,892 B.

`orchestrate-issues/SKILL.md` breaks down as:

- §4, 9,526 B, of which the owner-prompt blockquote is 1,857 B;
- §3, 5,775 B;
- §2, 5,320 B;
- §5, 4,009 B;
- the preface, 2,325 B;
- §1, 1,897 B.

Its fences hold 2,236 B.

The profiles that load a scoped file total 267,725 hot plus conditional bytes:
29,389 + 4 × (41,929 + 17,655). The 17,655 conditional bytes per host are the
`doc-grounded-questions` and `worktrees` documents, which S8 owns (#291 D8). They
stay unchanged, so every byte of the cut has to come from the scoped files.

### Targets

The measure is `just agent-instruction-load report --base 75784bed --head HEAD
--format json`. It sums hot plus conditional bytes over the profile-hosts of
`orchestration-dispatcher`, `release-owner` and `ship-release`, and the slice
needs `head ≤ 0.80 × 267,725 = 214,180` (D3). The per-file targets below are
ceilings, not goals:

| File | Base | Target |
|---|---|---|
| `ship-release/SKILL.md` | 30,869 B / 558 L | ≤ 20,500 B, ≤ 380 L |
| `ship-release/CHANGELOG.md` | 11,060 B / 224 L | ≤ 7,500 B, with `## Contents` |
| `orchestrate-issues/SKILL.md` (claude) | 29,389 B / 510 L | ≤ 24,000 B, ≤ 430 L |
| Codex stub | 1,035 B | ≤ 1,035 B |

At the targets the head is 4 × 28,000 + 24,000 + 4 × 17,655 = 206,620 bytes, or
77.2 % of base, leaving 7,560 B of slack. The binding constraint is ship-release:
its two files together must stay ≤ 29,890 B. Above that, even a full
orchestrate-issues cut misses the line.

The targets fit around the machine-read text:

- **ship-release.** Its fixed text is the fences, the marker and call, and the
  resolve paragraph, about 5.0 KB. That leaves 15.5 KB for prose, down from
  25.8 KB (−40 %).
- **CHANGELOG.** Its fixed text is the fences and template, 2.0 KB. That leaves
  5.5 KB for prose, down from 9.1 KB.
- **orchestrate-issues.** Its fixed text is the fences, the blockquote and the
  resolve paragraph, about 5.0 KB. That leaves 19 KB for prose, down from 24.4 KB
  (−22 %).

Section-by-section estimates of the cuts reach each target. The largest single
cuts are:

- Phase 5's repeated silent-rollback text;
- Phase 3's timeout rationale;
- Phase 4's restated guard grammar;
- the merged authorization and notes sections;
- orchestrate-issues' `expired` paragraph;
- the builder bullets;
- the `launch_refused` rationale.

### Content classes and their disposition

| Class | Examples in scope | Disposition |
|---|---|---|
| Helper-enforced rules | the guard's `gh pr merge` grammar and release-arm conditions; slot reservation and `max_parallel` handling; `build-delivery`'s resolution root and refusal shape; control's ownership of readiness, precedence and capacity | One line: run the command and act on its refusal (D6) |
| Duplicated text | `## The flow` restating every phase; standing authorization in both `## Standing authorization` and `## Notes`; silent rollback in Phase 5's invariant, failure list and CHANGELOG's Verification; `## Quality check` and `## Anti-patterns` restating Steps 2–4 | One home each. `## The flow` is deleted (D7); authorization lives in `## Standing authorization`; CHANGELOG keeps one checklist |
| Rationale and history | why Phase 0 resumes first; the explanation behind the 300 s foreground wait (the rule itself stays); why annotated; why `--notes-file`; the Claude-only note; `human_directed`'s authorization story; "what changelog shape this skill moved away from" | Cut. Git history and the prior specs keep it. One guard clause stays only where an agent would otherwise "simplify" a command into a known trap (D5) |
| Self-evident text | "Capture the PR number", "Don't paper over", the operator-audience paragraph, tone advice beyond one line | Cut |
| Machine-read text | listed under Decisions | Kept byte for byte (D4) |
| Wrong rather than wordy | — | Not edited; recorded in `### Findings to file` |

### Descriptions

All three descriptions are put in the third person with a trigger clause. Their
combined bytes must not exceed base (D8):

- ship-release: `Releases the integration branch …` (+1 B).
- orchestrate-issues, Claude: `Dispatches a set of tracker issues …` (+2 B).
- orchestrate-issues, Codex: `Reports that multi-owner orchestration is
  unsupported on Codex and names the sequential /from-issue route. Use for
  "orchestrate issues X, Y, Z" on Codex.` (153 B, down from 179 B).

The Codex stub's body is unchanged. It is already 21 lines, and every line is
either an instruction or its vetted command.

### Test-pin deletion (#291 D6)

The inventory at base, after #316:

- **`test_workflow_skill_contracts.py`**:
  - `test_contract_builders_state_the_resolution_root_and_relay_refusals` is
    deleted. It pins `BUILD_ROOT_CLAUSE` and `BUILD_REFUSAL_RELAY` on §3, and
    the constants go with it when nothing else uses them.
  - The `STDIN_CLAUSE` loop drops `ORCHESTRATE` and keeps `SHIP_ISSUE` (S5 owns
    it). `ORCHESTRATE` stays in `LIFECYCLE_DOCS`, whose `-` flag-value check is
    machine-read.
  - `test_the_bound_is_described_as_progress_not_phase` drops its
    `ORCHESTRATE` row and keeps the from-issue row.
  - `test_delivery_interface_two_is_one_atomic_production_caller_contract`
    takes `ORCHESTRATE` out of its multi-file prose corpus (#295 D13). Its
    `workflow_bootstrap` assertion is deleted, because `ORCHESTRATE_MACHINE_TEXT`
    already holds that token. A corpus phrase that then fails because only
    orchestrate-issues held it is deleted as a scoped prose pin.
  - `RETAINED_SUPPORT_CONTRACTS` loses its `ship-release/CHANGELOG.md` row, along
    with CHANGELOG's "receives the retained `ResolvedProject`" sentence
    (#295 D10).
  - The following checks are kept: `ORCHESTRATE_MACHINE_TEXT` (both trees); the
    owner-envelope `> \`field\`` lines; the closed action kinds; the
    `run_in_background` placement; the retired-verb absence;
    `~/.agents/bin/workflow-state`; the §3 request's 17-key set; the Codex
    stub's frontmatter and forbidden verbs; the D25 install-tree equality; the
    `SHARED_POLICY_ENTRIES` and `CLAUDE_POLICY_ENTRIES` rows, whose resolve
    paragraphs stay byte for byte; `test_build_delivery_callers_name_the_sanctioned_resolution_exception`, whose sentence orchestrate-issues keeps (D12); and the eval-corpus tests. `test_installed_policy_surface_matches_source_contract` reads the deployed tree against the same tables, so dropping the CHANGELOG row holds both before and after a switch.
- **`test_ship_release_contracts.py`**: everything is already machine-read. That
  covers the commands and their executable checks, the state-file keys, the two
  cross-file anchors, and the eval shape. The only change follows D7: the
  durable-state slice ends at `## Phase 0 — Pre-flight` instead of
  `## The flow`.
- **`WorktreesGuidanceTest`** reads only `worktrees/SKILL.md`, so it does not
  apply.
- **No change**: `test_dispatch_contracts` (the blockquote carrier),
  `test_shell_example_contracts`, `test_agent_model_matrix`, and
  `test_instruction_load`'s live-tree test. Their constraints bind the rewrite
  instead.

### `skill-lint-debt.json` and `instruction-load.json`

Four debt keys leave the file, each in the commit that clears it:

- `L2 …/ship-release/SKILL.md`
- `L2 …/orchestrate-issues/SKILL.md`
- `L3 …/ship-release/CHANGELOG.md`
- `L5 …/codex/…/orchestrate-issues/SKILL.md`

A key whose violation is gone fails the lint, and shrinking the debt file needs
no label.

`instruction-load.json` changes only through `just agent-instruction-load
tighten`. That lowers the hot ceilings of the three profiles, the corpus ceiling,
and the description ceiling (D2). Every commit keeps `just agent-workflow-tests`
green: it removes the debt keys that commit clears and re-runs `tighten`, as in
#295 D12. Other slices merge in parallel and share the corpus and description
ceilings, so `tighten` and the report re-run after every sync with the
integration branch.

### Eval plan

The pipeline cases are `EVAL_TREE=. just evals ship-release 5` and
`EVAL_TREE=. just evals orchestrate-issues 7`, each with `EVAL_MODEL` set to
`sonnet` and to `opus`. They run against the S3 baseline, which passed 5/5 on
both models for both cases in deployed mode. A case passes when its pass count is
at least the baseline's for that case and model.

Tree mode needs `CLAUDE_CODE_OAUTH_TOKEN`, and the token is not set here. The four
runs are therefore gated as in #295 D6 (D9):

- the Phase-6 owner runs them and commits their rows when the token is present;
- otherwise the evidence row is `human_pending`, and ship holds the issue as
  `needs-verification` with the four commands.

No result is claimed or copied from the baseline.

### Findings to file

These are filed as new issues after this phase, not fixed here. The text they
concern is kept as it is.

1. **ship-release reads its durable state before checking the checkout.** The
   state path `.superpowers/workflows/ship-release/state.json` is relative to the
   current directory. Phase 0 reads it at step 0, before step 1 moves to the main
   checkout. A release resumed from a feature worktree therefore misses its state
   file. This also contradicts `CLAUDE.md`'s claim that no `.superpowers/` path is
   rooted at the process cwd.
2. **ship-release's forge calls omit `--repo <resolved-repository>`.** This
   applies to Phase 0, Phase 3, 4.5, and CHANGELOG Step 1 (only the merge passes
   it). `gh` then derives the repository from Git, which the bindings section
   forbids.
3. **The ship-release wake prompt has the wrong argument.** Phase 5's wake prompt
   is `/ship-release <pr-num>`, but the skill's argument is a scope hint, so a
   wake seeds the merge subject with a PR number.

## Decisions

- **Machine-read text is kept byte for byte, in its current file** (#291 D6):
  - the `ship-release-owner` and `orchestration-issue-owner` markers and their
    `Agent(...)` lines;
  - the whole owner-prompt blockquote, including its four leaf-agent clauses and
    envelope lines;
  - every fenced command and every inline command the shell-example sweep vets;
  - the durable-state JSON and its keys;
  - the §3 control-request JSON;
  - the `build-delivery` input JSON and the owner-dispatch envelope fence;
  - every `workflow-state`, `launch-scope` and `resolve-project` argv;
  - every `ORCHESTRATE_MACHINE_TEXT` token;
  - both resolve paragraphs, including orchestrate-issues' `build-delivery` resolution-exception sentence (D12);
  - frontmatter, except the description (D8).
- **Anchors other documents cite keep their text** (D4):
  - orchestrate-issues keeps its numbered `## 1.`–`## 5.` headings, the
    "per-issue contract rule", §4's `delivery_contract` rule, the owner-object
    projection, the resume-pack step and the stop-pass sweep. `acquire-durable.md`
    and `CLAUDE.md` cite them.
  - ship-release keeps `## Durable release state` and `### 4.5d. Decide MAJOR /
    MINOR / PATCH`.
  - CHANGELOG keeps `## Version bump signals`.
  - ship-release's citation of `worktrees/SKILL.md`'s `## Shell forms the
    isolation checker refuses` stays true.
- **No semantic change.** Every pause condition, resume path, closed set, order
  and stop keeps its meaning. A sentence is cut only when one of these holds:
  - a helper enforces it and explains its refusal;
  - another section holds the same text;
  - it is rationale;
  - it is self-evident.

  A sentence that would change behaviour if read literally is kept or reported.

## Test seams

- `skill-lint check` covers L1–L5, the debt file's shrink, and the L2 body length.
- `just agent-instruction-load report`, `check` and `tighten` cover the measure,
  the ceilings and closure, and `just agent-instruction-budget` checks raise
  control locally (it must pass with no label).
- The existing machine-read checks inside `just agent-workflow-tests` are
  `test_dispatch_contracts`, `test_shell_example_contracts`,
  `test_agent_model_matrix`, `test_ship_release_contracts`, the kept
  `test_workflow_skill_contracts` checks, and `test_instruction_load`'s live
  tree.
- The eval harness, per the eval plan above. No new test pins prose.

## Out of scope

- `doc-grounded-questions`, `worktrees`, `agents/*.md`, `AGENTS.md` and every
  other skill (#291 D8). Anchors they hold that these skills cite stay.
- The behaviour and messages of helpers and of the lifecycle guard (D6), the
  gate's own files, and profile notes, membership or prompts (D2).
- `model-matrix.json`, evals content and fixtures.
- Workflow semantics, including the three findings above.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | No per-route reference files. The tracker-free and single-branch routes, the deploy watch (`deploy.adapter != none`) and orchestrate-issues' `unsupported` host route are cut in place in `SKILL.md`. Neither skill gains a file | `instruction_load` closure requires every file a `SKILL.md` names to be listed by each loading profile, a membership edit that `lowered_to` reads as a raise (#291 D2, #295 D5). Both ship-release profiles can take every route, so a route file would be conditional, and the measure sums hot and conditional (#291 Decisions). Orchestrate-issues' sections are one loop that every run executes, not exclusive routes | A `DEPLOY.md` or tracker-free route file: zero measured gain, and it needs the human-only label plus a ship-time human gate |
| D2 | `instruction-load.json` changes only by `tighten` (profile hot ceilings, the corpus ceiling and the description ceiling). No profile `note` gains a #298 sentence. `tighten` and the report re-run after every integration sync, and each commit removes its own debt keys (#295 D12) | `lowered_to(model, base) != base` treats any note edit as more than lowering a ceiling. The label is human-only (`rejections/ungated-agent-merges.md`) | Appending #298 note sentences as S4 did: S4 needed the label anyway; here a note would be the only reason to need it |
| D3 | The slice is held to the issue's literal measure: hot plus conditional bytes over the five profile-hosts of `orchestration-dispatcher`, `release-owner` and `ship-release`, base 267,725 at `75784bed`, head ≤ 214,180. The per-file ceilings are SKILL ≤ 20,500 B / 380 L, CHANGELOG ≤ 7,500 B, orchestrate ≤ 24,000 B / 430 L, which give 206,620 at target | Unlike #295 D1, the literal measure is reachable: the S8-owned 17,655 B per host is only 26 % of base. Ship-release counts four times, so it carries the cut | A scoped-file-share measure as in #295 D1: unnecessary here, and weaker than the acceptance criterion's wording |
| D4 | Every anchor another document cites keeps its text and its file. The anchors are the numbered orchestrate headings and the rules that `acquire-durable.md` and `CLAUDE.md` name, the CHANGELOG ↔ SKILL heading anchors, and the `worktrees` heading ship-release cites. The owner-prompt blockquote stays whole | #291 D8 (citers belong to other slices); `test_ship_release_contracts` anchor test; `test_dispatch_contracts` blockquote carrier | Renumbering or renaming sections while cutting: it breaks citers the slice cannot edit |
| D5 | Rationale is cut outright, and no ADR is written. One guard clause stays only where it stops a plausible wrong rewrite of a command: `targetCommitish` holds a branch name; `--merged` excludes unmerged tags; the no-PR path tags the local `<default>`; a health 200 is not proof; a shell variable does not survive between calls | The Bar (Token economy; Moves keep their history) and #291 Decisions ("cut unless an agent without it would get the step wrong"). `bindings.paths.context` is empty, so the project binds no decision-record directory | Moving rationale into new ADR files: there is no bound ADR directory, and it would add unread corpus bytes |
| D6 | No helper or guard edits. A helper-enforced rule becomes "run X; act on its refusal": the release arm of `gh pr merge` defers to the guard; slots and capacity defer to `control`; the builder's root and refusal defer to `build-delivery`'s stderr line, which the final report relays verbatim. The merge subject's forbidden characters stay as one line, because breaking that rule wastes a guarded call | `lifecycle_guard.validate_release_merge` and the builder's refusal already name the violated rule. #291 permits improving error text but does not require it (#295 D7) | Rewording guard or `workflow-state` messages: changes a helper and its tests for no byte gain |
| D7 | `ship-release`'s `## The flow` is deleted, and `test_ship_release_contracts`' durable-state slice re-points its end anchor to `## Phase 0 — Pre-flight` in the same commit | It restates the phase headings, and only that test reads the heading (#291 D6 allows renaming test-only anchors) | Keeping a shortened flow: the remaining ~400 B are counted four times over and duplicate the phase headings |
| D8 | All three descriptions move to the third person with a trigger clause, and their combined bytes stay ≤ base (511 B → 488 B), so the description ceiling only lowers | #291 D9; skill-lint L5; `description_ceiling_bytes` currently equals its measure (3,145), so any net growth would breach the ceiling and need the label | Keeping "Never launches owners." in the Codex description: the body already says it, and every session pays for description bytes |
| D9 | The four tree-mode evals run only with `CLAUDE_CODE_OAUTH_TOKEN` present. Otherwise the evidence row is `human_pending`, and ship holds the issue `needs-verification` with the four commands | #295 D6; #291 D7; the token is unset in this environment; the baseline rows are deployed-mode | Deployed-mode runs after `just switch`: they change the live machine and evaluate the deployed tree, not this one. Reusing the baseline rows would be fabrication |
| D10 | Tests: delete the prose pins inventoried above, keep every machine-read check, and drop scoped files from multi-file prose corpora without deleting other slices' assertions (#295 D11, D13). Write no replacement pins | #291 D6; `docs/standards/agent-helpers.md` rule 6 | Deleting a whole multi-file test: it removes pins S5 owns |
| D11 | Rules found to be wrong rather than wordy stay unedited and are listed in `### Findings to file`: state read before the checkout check, forge calls without `--repo`, and the wake prompt's argument | #291 Out of scope: no workflow-semantics change; the issue says to file such rules as new issues | Fixing them in this slice: behaviour changes inside a no-semantics slimming PR |
| D12 | Orchestrate-issues keeps its sentence naming `workflow-state build-delivery` as the only sanctioned resolution exception byte for byte, and its multi-skill test stays unchanged | Grill: `test_build_delivery_callers_name_the_sanctioned_resolution_exception` binds every `build-delivery` caller across three skills to one resolution-contract statement, the same class as the resolve paragraph #295 D10 kept; it costs one load of about 250 B | Cutting it and excluding orchestrate-issues from the test: one caller would diverge from a shared policy statement that S5's ship-issue still carries |
| D13 | AC3's base stays 267,725 B at `75784bed` across every integration sync; the head is whatever `report --head HEAD` measures, other slices' merged cuts included, and the per-file ceilings stay the slice's own floor | The issue measures "against `main` at the slice's base"; profile membership is unchanged, so `report --base 75784bed --head HEAD` is one comparable command | Re-basing on each sync's `origin/main`: it lets another slice's growth or cut move this slice's threshold |
| D14 | `test_lifecycle_calls_are_single_stdin_commands_on_interface_two` keeps its flag-value, `--result-file` count and `"interface_version": 1` checks for every path, and applies its English forbidden phrases only to paths outside this slice's scope | #295 plan review R3 (same change for from-issue); #291 D6 counts an English absence pin as a prose pin | Leaving the English phrases on `ORCHESTRATE`: AC5 would keep a prose pin on a scoped file |
| D15 | All three scoped descriptions change in one commit (the plan's Task 1), before that commit's first `tighten`, and the Codex stub's L5 key is cleared there too | Phase-5 Codex review R1: `description_ceiling_bytes` sits at its measured 3,145 B, so the +1 B and +2 B edits would breach before the stub's −26 B, and `tighten` exits 1 on a breach | One description per task: the first two commits fail the gate. Reordering the stub first: its `tighten` consumes the slack the later edits need |
| D16 | The Claude orchestrate-issues description keeps its base text ("Dispatch a set …", 154 B) instead of D8's "Dispatches …" (156 B); it supersedes D8 and D15 for that one text | Task 1 implementer and task review: after Task 1's `tighten` the description ceiling equals its measure (3,120 B) and the `orchestration-dispatcher` hot ceiling equals its measure, so the +2 B change would need the `instruction-budget-raise` label, which no agent may apply | Changing the description in Task 3: the descriptions ceiling still breaches whatever the body cut, and raising it needs the human-only label |
| D17 | The plan's Global Constraints line "Machine-read text stays byte for byte …" (its clause on every inline command span the shell-example sweep vets) yields to Task 3 Steps 3.5 and 3.8, which remove two spans from the Claude orchestrate-issues `SKILL.md`: bare `resolve-project` in the D6-dropped builder resolution-root sentence and `workflow-state host-route --route codex` in the deleted `## Notes`; neither is machine-read from that file (the host-route token is pinned on the Codex stub) | Task 3 implementer and task review | Keeping both spans: it would keep a D6-dropped sentence and a `## Notes` section whose only machine-read content already lives on the Codex stub |
| D18 | `test_no_skill_prescribes_a_sibling_candidate` (test_workflow_skill_contracts.py) stays: a corpus-wide absence guard that applies to every skill and pins no text of a scoped file is not a scoped prose pin | Task 4 review; D10 (do not delete other slices' assertions), D14 | Deleting it for AC5: it guards every slice's skills and pins nothing in a scoped file |
