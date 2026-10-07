# Slim sdd to skill best practices (#297)

Slice S6 of program [#291](https://github.com/fagenorn/nix-config/issues/291).
The program spec (`2026-10-07-issue-291-skill-best-practices-design.md`) binds
this slice, and its rows are cited here as "#291 D<n>" without being restated.
The sibling slice S4 (`2026-10-07-issue-295-slim-from-issue-design.md`) is the
template; its rows are cited as "#295 D<n>". This spec's own rows are in
`## Decision ledger` below.

## Problem

Every lifecycle owner that reaches Phase 6 pays for all of `sdd`. The eight
scoped documents total 93,317 bytes at the slice base `baac2897`. Each of the
three profile-hosts that run Phase 6 loads all eight of them, hot or
conditional:

- `SKILL.md` is 433 reflowed body lines against the slice's 300-line target.
- The review-package gate is spelled out five times: in the cumulative
  delivery gate, the task loop, the fix loop and twice in `final-review.md`.
  Each copy restates what `review-package`, `artifact-budget validate-report`
  and `artifact-budget check` already enforce.
- The controller documents explain the review-package manifest interface
  versions 2 and 3: the EF Core designer evidence, the context sequence and
  the packing policy. That is what the producer does and what the reviewers
  check. The controller never acts on it, and each reviewer payload already
  carries its own copy.
- Rationale and history sit on the hot path: the D-number trails, "in the
  review study the cheaper tier missed…", why per-finding fixers cost more,
  and the fix loop's rationalizations table, which restates rules stated just
  above it.
- `final-review.md` (276 reflowed lines) and `fix-loop.md` (114) exceed 100
  lines without a `## Contents` list. These are the slice's two
  `skill-lint-debt.json` keys.
- The five payloads are pasted into every subagent dispatch, so each one is
  paid for once per dispatch on top of its load in the controller. Four of
  them repeat a 1.2–1.9 KB manifest-reading paragraph, and their preambles
  restate who the reviewer is in prose that the dispatch marker already
  carries.

The issue's prose-pin deletion is mostly done already: the #313 prefactor
replaced the sdd pins with `SDD_MACHINE_TEXT`. Five assertions over scoped files
remain, listed under `### Test changes`.

## Solution

Keep the eight files and their roles. Cut each one by content class, give the
review-package gate one home in `SKILL.md`, and tighten the two profiles'
ceilings. No file is added, removed or reclassified, and no profile note
changes, so `instruction-load.json` changes only by lowering ceilings. The
slice therefore needs no `instruction-budget-raise` label (D2).

### Target layout

All paths are under `home/common/agent-skills/skills/sdd/`. The profiles are
**O** (`orchestrated-issue-owner`, host claude) and **I**
(`implementation-owner`, hosts claude and codex). The fourteen `sdd-*` leaf
profiles name a scoped file only as their `prompt` source, which is not
measured, and their `prompt` fields and dispatch sites do not change.

| File | Holds after the slice | O | I |
|---|---|---|---|
| `SKILL.md` | the resolve and review-routing paragraph; setup (worktree, plan check, workspace and ledger, initial validation); `### Cumulative delivery gate`; `### Review-package gate` (new heading, the one home of the gate); `## Agent tiers` (tiers, the compressed re-evaluation rule, the leaf clauses); the task loop with `### Lifecycle workers` and steps 1–5; the final-review pointer; `## Finish` | hot | hot |
| `final-review.md` | `## Contents`; axis routing; acceptance-criteria block; dispositions and acceptance verdicts; fixer; scoped re-reviews; `## Acceptance record`; `## Final verification` | hot | hot |
| `fix-loop.md` | the five rounds with their six sites; lifecycle-worker line; scoped re-review; the breaker. Under 100 reflowed lines, so it needs no `## Contents`; if it ends over 100, it carries one | cond | cond |
| `implementer-prompt.md` | two sites and one fence | hot | hot |
| `task-reviewer-prompt.md` | one site, one fence and the placeholders | hot | hot |
| `re-review-prompt.md` | one site, one fence and the placeholders | cond | cond |
| `conformance-reviewer-prompt.md` | one site, one fence and the placeholders, with the non-SDD fallback ship-issue uses | hot | hot |
| `correctness-reviewer-prompt.md` | one site, one fence and the placeholders, with the scoped literal-path fetch diff-review uses | cond | hot |

The classifications are today's. File names, the dispatch marker homes and
`DISPATCH_MARKER_TOTAL` (39) are unchanged (#295 D3).

### Content classes and their disposition

| Class | Where it is today | Disposition |
|---|---|---|
| Duplicated gate | the review-package exit gate in `SKILL.md` §Cumulative delivery gate, §2 (twice), `fix-loop.md` and `final-review.md` (twice) | One home: `SKILL.md`'s `### Review-package gate` states it once. That covers recording the full base and head SHAs, running the producer, piping its stdout through the producer validator, the independent `artifact-budget check --kind review-package` with all four metrics compared, and the three exit routes. The other sites say "apply `SKILL.md`'s review-package gate" (D3) |
| Producer and reviewer detail | the version 2 and 3 manifest paragraphs in `SKILL.md`; the per-version manifest paragraph and the reviewer-side reading rules in `final-review.md`; what the task reviewer reads, in §3 | Cut from the controller documents. The producer enforces them and every payload keeps its own reading rule (D4) |
| Helper-enforced rules | the plan-check metric shape; the `validate-report --boundary sdd` field rules (for example, `unmet` under `clean`); `mark-progress` outcomes; `launch-commit` refusals | One line each: run the command and act on its refusal. Where the refusal does not say what to do, one mapping line stays (D7) |
| Rationale and history | D-number trails such as "(D5, D6, D8)", "the D15 publication contract" and "(parent D3)"; the review-study sentence; the per-finding-fixer cost story; "turn count beats token price"; "why" clauses in the fix loop; `## Common rationalizations` | Cut. Each already lives in the accepted spec it came from |
| Self-evident text | "Subagents never inherit your session's history"; restated "never inline"; prompt-level exhortations the payload already carries | Cut |
| Payload preamble | the prose outside each payload's fence that repeats the purpose, the model and the reader's identity | One line before the marker. The placeholder list stays, because the controller fills it in |
| Payload manifest paragraph | four reviewer payloads, 1.2–1.9 KB each | One compressed paragraph per payload. Payloads stay self-contained and share no block (D5) |
| Machine-read text | listed in D8 | Byte for byte, in its current file |
| Wrong rather than wordy | — | Not edited. Recorded in `### Findings to file` (D7) |

### Byte and line targets

Measured at base `baac2897` with `just agent-instruction-load report --base
origin/main --head HEAD --format json`. Each of the three profile-hosts (O
claude, I claude, I codex) lists all eight scoped files hot or conditional, so
the **sdd share** is 3 × 93,317 = 279,951 bytes. The slice is held to `head ≤
0.65 × base`, which is `head ≤ 181,968` (D1); the issue's amendment sets the acceptance line at `head ≤ 0.80 × base`, `≤ 223,960` (D19), and 0.65 stays this design's aim. The whole-profile totals (O
claude 175,587 hot plus 153,836 conditional; I claude 172,466 plus 135,765; I
codex 172,466 plus 119,354) are reported beside the share. They cannot fall by
35% from this slice alone, as #295 already recorded.

Per-file targets. Each is a ceiling, not a goal; the reflowed-line counts are
measured with `skill_lint.reflowed_lines`:

| File | Base bytes (lines) | Target bytes | Line target |
|---|---|---|---|
| `SKILL.md` | 27,839 (433 body) | ≤ 14,500 | ≤ 230 body lines |
| `final-review.md` | 17,096 (276) | ≤ 10,500 | — (carries `## Contents`) |
| `fix-loop.md` | 6,782 (114) | ≤ 4,300 | ≤ 95 |
| `implementer-prompt.md` | 7,546 | ≤ 5,200 | — |
| `task-reviewer-prompt.md` | 10,280 | ≤ 6,000 | — |
| `re-review-prompt.md` | 6,564 | ≤ 4,200 | — |
| `conformance-reviewer-prompt.md` | 9,713 | ≤ 6,500 | — |
| `correctness-reviewer-prompt.md` | 7,497 | ≤ 5,200 | — |

At the targets, one host loads 56,400 bytes, so the share is 169,200 (60.4% of
base). That leaves 12.8 KB of slack under the 0.65 line, so a single overshoot
does not fail the slice. `SKILL.md` and `final-review.md` are where an
overshoot costs the most. The hard lines are the share (AC3) and `SKILL.md` ≤
300 reflowed lines (AC2), now ≤ 500 per the amended issue (D19). A file over its target is allowed only when every
remaining sentence is machine-read or carries a rule, and the commit body must
then name the file and its size.

### Cutting rules per document

- **`SKILL.md`.**
  - The opening paragraph stays a no-resolve rule: no `resolve-project resolve`
    text, because the shared-policy test set would otherwise enrol the file.
  - The workspace bullet keeps the `scripts/sdd-workspace PLAN_FILE` command
    and the `<primary-checkout>/.superpowers/sdd/<checkout-bucket>/<plan-basename>/`
    literal, and cuts the explanation of why that path is not cwd-rooted.
  - The ledger rules keep the three formats `workflow-state resume-pack`
    parses (D8). §Lifecycle workers keeps every argv and the carrier sentences
    byte for byte. Its refusal routing becomes a decision list. The
    `mark-progress` paragraph becomes two lines: run it before the first task
    and after each `complete` line, and its refusal never stops the loop.
  - §2 keeps the four status routes and the BLOCKED escalation site.
  - **Interim child results** keeps its heading and every rule (re-engage the
    same child; you may end your turn; no text-only reply, suspension or
    replacement; the worker stays registered; an undeliverable message goes to
    from-issue's **Writing workers** route) in about half the words (D10).
  - `## Finish` keeps the eleven report fields, the `review_state`,
    `verification_state` and `acceptance_state` derivations, the two
    detail-publication routes and both terminal states. It drops the contrast
    with ship-issue's root.
- **`final-review.md`.**
  - It opens with `## Contents`.
  - The configured-review paragraph shrinks to the three routing rungs and the
    routing-error rule. `codex-collaboration`'s `diff-review` owns transport,
    capacity and fallback, so those details are cut here.
  - The acceptance-criteria block keeps the tracker read argv, the criterion
    line definition, the `Declared verification:` line and the
    no-criterion-source and blocked-tracker routes.
  - `## Acceptance record` keeps its schema fence (labeled `markdown`), its
    freshness rule and the lifecycle commit argv.
  - `## Final verification` keeps the four numbered steps, the `verified-tree`
    argv and the ledger line format.
- **`fix-loop.md`.**
  - The rounds stay with their six sites, in order. The round-4 explanation
    shrinks to one clause: three failures on the same context escalate the
    model, not only the context.
  - The re-review paragraph points at `SKILL.md`'s review-package gate. The
    fix-round ledger line format and the three breaker outcomes stay.
  - `## Common rationalizations` is cut.
- **Payloads.**
  - Inside the fence, each payload keeps its `Subagent (...)` header lines, its
    placeholders, its four leaf clauses (each exactly once after `prompt: |`)
    and its output format. Its rubric bullets stay, with redundant wording cut.
  - The manifest paragraph keeps the rules a reviewer applies: validate the
    coverage and bytes against the four metrics; read every shard once, in
    order; report an unreadable or mismatched shard; for version 3, honor
    `packaging.context_lines` and `stable-first-fit-whole-file` and read the
    live file when context is short; for version 2, and for version 3 with
    `generated_evidence`, corroborate against the companion migration and
    snapshot diff and the three implementer evidence items; never treat that
    evidence as a waiver.
  - `conformance-reviewer-prompt.md` keeps the `git diff --stat`/`git diff`
    fallback and the omit rules for `[ACCEPTANCE_CRITERIA]` and
    `[DEFERRED_AND_PARKED_LINES]`, which ship-issue's full review uses.
  - `correctness-reviewer-prompt.md` keeps the scoped literal-path fetch, its
    one-invocation-per-path rule, the `scoped to <N> of <M> product files;`
    clause, and the Critical, Important and Minor headings that diff-review
    validates.

### Test changes

The inventory at base is small, because #313 already deleted the sdd prose pins
(#291 D6, #295 D11):

1. `test_durable_review_detail_precedes_every_removable_cleanup`: `self.sdd`
   leaves the `report_path` / `keep the worktree` loop. Its
   `.superpowers/issue-delivery/` assertion on `self.sdd` stays, because the
   literal is the producer's destination root (D8); the literal moves from the
   cut task-loop preamble into `## Finish`.
2. `test_fixture_producer_states_supplement_behavioral_cli_cases`: `self.sdd`
   leaves the loop. `complete` and `within_budget` are kept for `SKILL.md` as
   the checker values it gates on, and `contract error` goes.
3. `InterimChildResultContractsTest`: `SDD` leaves `OWNERS`, the identical-copy
   comparison and the section table (D10, #295 D13). The from-issue and
   ship-issue assertions are untouched.
4. `SHARED_POLICY_SUPPORT` and `RETAINED_SUPPORT_CONTRACTS` lose their
   `sdd/conformance-reviewer-prompt.md` rows, together with the sentence they
   pin outside the fence. The no-resolve clause inside the fence stays
   (#295 D14).
5. `SDD_MACHINE_TEXT` items follow their text. `member_count`,
   `aggregate_bytes` and `stable-first-fit-whole-file` leave the `SKILL.md`
   tuple, and `stable-first-fit-whole-file` leaves the `final-review.md` tuple,
   because the controller no longer explains packing. `PRODUCER_VALIDATION`
   leaves the `fix-loop.md` and `final-review.md` tuples, because the gate's
   argv now lives only in `SKILL.md`. Their range argv
   (`review-package PLAN_FILE DELIVERY_BASE DELIVERY_HEAD`) stays (D15). Every
   other item stays in its file. `test_sdd_report_is_exact_and_mechanically_validated` stays as
   it is, because it covers a JSON key set.

These checks stay green unchanged: `test_dispatch_contracts` (five fence
carriers and the `## Agent tiers` section carrier; any scoped file with exactly
one unlabeled fence must be enrolled, so new or reworked fences outside the
payloads are labeled), `test_agent_model_matrix`, `test_shell_example_contracts`
(inline commands keep their whole-allowed form), the nested-dispatch tests,
`test_instruction_load`'s live tests and `test_eval_cases`. No new test pins
prose. Parallel slices delete their own entries from the same shared
structures (#296 takes `SHIP_ISSUE` out of `OWNERS`), so a sync conflict there
resolves to the union of both slices' deletions (D16).

### Review-package bound (the #312 lesson)

`review-package` refuses a range in which any one file's diff exceeds the
65,536-byte member limit. It also refuses more than eight members, or more
than 524,288 bytes in aggregate (`artifact-budget describe --kind
review-package`). #295's part 1 had to be split because its test-file diff
reached 70 KB. Here the largest net diff is `SKILL.md`: at most 27.8 KB removed
plus 14.5 KB added, about 45 KB with context. The test-file diff is estimated at under 10 KB.
The whole branch, with the spec and plan included, is estimated at about
170 KB. The plan keeps every file's net branch diff ≤ 48 KB (D13). If one would
pass that, the plan splits that file's rewrite across two PRs instead of
letting the cumulative gate refuse the branch late.

### `instruction-load.json` and `skill-lint-debt.json`

- `skill-lint-debt.json` loses `L3 …/sdd/final-review.md` and
  `L3 …/sdd/fix-loop.md`, each in the commit that clears it (a stale key fails
  the lint). Shrinking the debt file needs no label.
- `instruction-load.json` changes only through `just agent-instruction-load
  tighten`. That lowers O's and I's hot and conditional ceilings to the
  measured values; no member, note or other field changes. `instruction_load
  check` must therefore report no `raise:` line on this PR, and one would mean
  the design was broken, not that a label is needed (D2).
- Parallel slices edit the same two profiles: #295's remainder changes O's and
  I's from-issue membership, and #296 changes the ship-issue members. After
  every integration-branch sync the owner re-runs `tighten` and the report and
  takes the measured values (#295 D12).

### Eval plan

The scoped skill has one pipeline case, `sdd` case 4
(`planned-worktree-executes-and-stops-before-final-review`). Its S3 baseline
rows of 2026-10-07 are 6/6 PASS on `sonnet` and 6/6 PASS on `opus`, in
deployed mode. The criterion is `EVAL_TREE=. EVAL_MODEL=<model> just evals sdd
4` with `passed` ≥ 6 on each model. The case stops before the final review, so
it exercises `SKILL.md`, the implementer payload and the task-review payloads,
but not `final-review.md`. The gate is the one #295 D6 set: the two runs happen
only when `CLAUDE_CODE_OAUTH_TOKEN` is present (it is unset in this
environment). Otherwise the AC row is `human_pending` with the two commands,
and nothing is copied from the baseline (D14).

### Findings to file

These are filed after this phase, not fixed here:

1. `skill-lint check` still has no `--max-body-lines` flag. The 300-line check
   uses `skill_lint.reflowed_lines` over the body that `parse_frontmatter`
   returns (#295 D8). This is the same finding #295 filed, so the plan files it
   only if no issue for it exists yet.

## Decisions

- **Same files, smaller.** There are no new files, splits or deletions. Every
  sdd branch is one that both loading profiles can take inside Phase 6, so a
  route file would be hot or conditional in both. Moving bytes there does not
  count toward the target (#291 Decisions), and it would cost the label.
- **One home per rule.** `SKILL.md` owns the review-package gate, the leaf
  clauses, the lifecycle worker rules and the report. `fix-loop.md` and
  `final-review.md` name `SKILL.md` sections by heading, never each other (L4).
  The payloads name nothing.
- **Payloads stay self-contained.** Each payload is pasted whole into a
  subagent that has no other access, so a payload repeats what its reader
  needs and is cut only for redundancy within itself.
- **No semantic change.** Every gate, order, closed set, tier, cap and stop
  keeps its meaning. A sentence is cut only when a helper enforces it, another
  home holds it, or it is rationale. A sentence that would change behavior if
  read literally is kept or reported (D7).
- **Anchors other skills, helpers or tests cite stay true** (D9).

## Test seams

- `skill-lint check` (L1–L5 and the shrink-only debt file), plus
  `skill_lint.reflowed_lines` over `SKILL.md`'s body for the 300-line target.
- `just agent-instruction-load report`, `check` and `tighten` for the share,
  the ceilings and the absence of any `raise:` line, with `just
  agent-instruction-budget` run locally.
- The existing machine-read checks inside `just agent-workflow-tests`:
  `test_dispatch_contracts`, `test_agent_model_matrix`,
  `test_shell_example_contracts`, `SDD_MACHINE_TEXT`, the sdd report key-set
  test, and `test_workflow_state`'s resume-pack ledger parsing.
- The eval harness for behavior, gated by D14. No new test pins prose.

## Out of scope

- Other skills' documents, even where they cite sdd: `from-issue`,
  `ship-issue`, `codex-collaboration`, `writing-plans`, `retro`,
  `agents/*.md` and `AGENTS.md` (#291 D8).
- Helpers and their error text, `model-matrix.json`, dispatch sites, profile
  `prompt` fields, notes and membership, and the gate files.
- `scripts/sdd-workspace`, `scripts/task-brief` and the evals directory.
- Workflow semantics: tiers, rounds, caps, lanes, review axes, report shapes
  and ledger formats.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The −35% target is measured as the sdd share: the bytes of `sdd/` members each loading profile-host lists hot or conditional, summed over O claude, I claude and I codex; base 279,951, head ≤ 181,968; the whole-profile totals are reported beside it | #295 D1; #291 D8 gives each document one owning slice | The literal whole-profile sum: those profiles are mostly other slices' documents |
| D2 | Label-free slice: no file is added, split, deleted or reclassified and no note changes, so `instruction-load.json` changes only by `tighten` lowering ceilings; a `raise:` line is a design defect, not a label request. Differs from #295 D5 because sdd has no route that a loading profile cannot take | Both O and I run every sdd branch in Phase 6; #291: moving bytes between hot and conditional does not count; #291 D2: only lowering is label-free | Per-branch route files (BLOCKED, publication failure, final verification): hot or conditional in both profiles, so no share gain, and they cost the human label |
| D3 | The review-package gate gets one home, `SKILL.md`'s new `### Review-package gate`; the cumulative gate, step 2, the fix loop and both final-review uses apply it by name; naming `SKILL.md` is L4-legal | The Bar, DRY; #291 "rules a helper enforces become one line" | Keeping a copy per site: five texts that must change together |
| D4 | The manifest interface-version detail (v2 EF designer evidence, v3 context sequence and packing) leaves the controller documents; the payloads keep the reader rule. `member_count`, `aggregate_bytes` and `stable-first-fit-whole-file` leave `SKILL.md`'s `SDD_MACHINE_TEXT` tuple, and `stable-first-fit-whole-file` leaves `final-review.md`'s, with the text | The producer selects and validates the version; the controller only gates on exit codes and metrics; reviewers consume the fields | Keeping it in `SKILL.md` for completeness: three loads of text no controller step acts on |
| D5 | Payloads stay self-contained: no shared include file. Each keeps its four leaf clauses, its placeholders and its output format, and its manifest paragraph is compressed in place | Payloads are pasted verbatim into subagents with no other access; `test_dispatch_contracts` fence carriers; #291 D4 | A shared `review-common.md` pasted beside each payload: a new reference file read and pasted by the controller changes dispatch construction and needs the label |
| D6 | The Sonnet re-evaluation rule stays in `## Agent tiers`, compressed to its metric, baseline (84%, 153), floor (about 10 issues, at least 30 reviews) and threshold (< 74% reverts the two named sites) | #270 D4 chose this home; the issue forbids semantic change | Moving it to a spec or tracker issue: reverses #270 D4 outside its owner, and the rule's home is not wordiness |
| D7 | No helper is edited; where a refusal does not say what to do, a one-line mapping stays; a rule found wrong is recorded in `### Findings to file` | #295 D7; #291 Out of scope | Rewording helper messages: helper and test changes beyond this slice for no byte gain |
| D8 | Machine-read text is kept byte for byte, in its file: dispatch markers and `Agent(...)` lines; the four leaf clauses in `## Agent tiers` and in each payload fence; the ledger formats `workflow-state resume-pack` parses (`# SDD ledger — plan: <plan file path>`, `Task <N>: complete`, `Task <N>: fix round`); the eleven SDD report keys and their value sets; helper argv (`workflow-state`, `launch-commit`, `launch-scope`, `review-package`, `artifact-budget`, `verified-tree`, `scripts/task-brief`, `scripts/sdd-workspace`); the workspace and `.superpowers/issue-delivery/` literals; payload placeholders; the reviewer output tokens the controller or diff-review reads (status values, `launch fence refused: <reason>`, ADDRESSED / NOT ADDRESSED, the axis verdict lines, the `### Acceptance` columns, the Critical/Important/Minor headings, `scoped to <N> of <M> product files;`) | #291 D6; `SDD_LEDGER_HEADER`/`SDD_TASK_LINE` in `workflow-state`; `DIFF-REVIEW.md` validates the headings | Treating only test-pinned text as machine-read: the resume pack and diff-review parse unpinned text |
| D9 | Anchors other skills and tests cite stay: `### Lifecycle workers` and the `progress.md` check (from-issue), `## Agent tiers` (carrier), `### 2. Handle the report` and **Interim child results**, `## Finish` and the report fields (from-issue, ship-issue), `## Acceptance record` and `## Final verification` (ship-issue's verified-tree use), every file name, and the payload fallbacks ship-issue REVIEW.md and codex-collaboration DIFF-REVIEW.md rely on | #295 D9; #291 D8 | Re-pointing the citers: edits documents other slices own |
| D10 | sdd's **Interim child results** paragraph is compressed with every rule kept, and `SDD` leaves `InterimChildResultContractsTest`'s owners, identical-copy and section checks | #295 D13; #291 D6 deletes scoped prose pins | Keeping the identical copy: a prose pin on a scoped file that freezes 1.1 KB in three loads |
| D11 | Tests: the five edits in `### Test changes` only; machine-read assertions stay; no replacement pins | #291 D6; `docs/standards/agent-helpers.md` rule 6; #295 D11 | Re-adding "concept present" checks: #291 D6's rejected alternative |
| D12 | Every plan task keeps the gate green at its own commit: it drops the debt key it clears and runs `tighten`; the last task re-tightens after the final sync and measures | #295 D12; `LiveBudgetTest` runs breach and tightness on every commit | One closing task for ceilings: every earlier commit fails `just agent-workflow-tests` |
| D13 | No changed file's net branch diff may exceed 48 KB (member limit 65,536); the plan checks each file's diff size per task, and a file that would pass it splits across PRs | #312: #295 part 1 split after a 70 KB test-file diff; `artifact-budget describe --kind review-package` | Discovering the breach at the cumulative gate: late, and forces an unplanned split |
| D14 | Eval: `sdd` case 4 on sonnet and opus, pass ≥ 6 each, run only when `CLAUDE_CODE_OAUTH_TOKEN` is present; otherwise the AC row is `human_pending` with both commands | #295 D6; S3 baseline rows 6/6 and 6/6; #291 D7, D11 | Copying the baseline as the result: fabrication; running deployed mode: needs `just switch` |
| D15 | The review-package gate's validation argv (`artifact-budget validate-report --boundary producer --input -`, `artifact-budget check --kind review-package`) appears only in `SKILL.md`'s `### Review-package gate`; `fix-loop.md` and `final-review.md` keep only their range argv and apply the gate by name, and their `SDD_MACHINE_TEXT` tuples drop `PRODUCER_VALIDATION`; refines D3 | Grill: D3's single home would otherwise leave three pinned copies; #291 D6 keeps a machine-read pin only where a reader consumes the text | Keeping the argv in each site "for the reader": the five-copy duplication D3 removes |
| D16 | A sync conflict in a test structure shared with a parallel slice (`InterimChildResultContractsTest.OWNERS`, the policy-support tables, `SDD_MACHINE_TEXT` neighbours) resolves to the union of both slices' deletions, never to either side alone | #291 D8: each slice deletes only its own documents' pins; #296 edits the same test file | Re-running one side's edit over the other: silently restores the other slice's deleted pin |
| D17 | When `PRODUCER_VALIDATION` leaves it (D15), `fix-loop.md`'s `SDD_MACHINE_TEXT` entry is deleted whole, with no replacement item such as its `review-package PLAN_FILE FIX_BASE HEAD` range argv | D11 (no replacement pins); an empty tuple asserts nothing | Pinning the fix-range argv instead: a new pin this slice's test policy rules out |
| D18 | Execution starts from a branch that contains `origin/main`: the sdd controller merges it before Setup pins `DELIVERY_BASE`, and a conflict stops. The tasks cut the synced text and keep #281's `blocked_on=deadline` paragraph in `### Lifecycle workers` in its tested order. AC3's base stays `baac2897` (D1), with the synced-base share reported beside it | #320 and #321 (#281) changed `sdd/SKILL.md`, the test file and `instruction-load.json` after `baac2897`; sdd pins `DELIVERY_BASE` once at Setup; `test_sdd_states_the_deadline_suspension_order` reads that paragraph | Cutting the `baac2897` text and leaving #281 to ship's sync: a foreseen whole-file conflict resolved outside task review. Merging inside Task 1: the pinned base would put #320/#321 in every cumulative review package |
| D19 | The acceptance lines follow the issue's 2026-10-07 amendment: `SKILL.md` ≤ 500 reflowed lines (skill-lint L2) and the sdd share head ≤ 0.80 × base (≤ 223,960); the per-file targets stay as ceilings, and none is met by moving a cited anchor or changing semantics; supersedes the 300-line and 0.65 lines in D1 and § Byte and line targets | Issue #297 body amended by the #291 program owner after #296 showed the old lines conflict with keeping cited anchors and semantics | Keeping the stricter lines as hard gates: invites the anchor cuts the amendment forbids |
| D20 | Task 6 checks that the branch contains `origin/main` before reading any budget line; when it does not, it stops with `needs sync` for the controller's sync and remeasurement instead of calling a `raise:` a design defect | Phase-5 Codex plan review R2: the budget recipe compares the complete model against `origin/main`, so a parallel slice landing (#296) can fail it independently of this slice | Treating every `raise:` as a D2 design defect: misattributes another slice's landing |
