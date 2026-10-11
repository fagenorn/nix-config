# Issue 354 — design leaves a code map for the planner

Issue: https://github.com/fagenorn/nix-config/issues/354

## Triage

Input: `{"signals":{"contract_change":{"value":"hit","evidence":"The design producer gains a second output (code map) and the planning dispatch brief gains a required input naming it; both are inter-agent contracts."},"concurrency_or_persistence":{"value":"no","evidence":"Skill text, evals and at most an artifact-budget kind; no locking or persisted ledger state."},"open_design_questions":{"value":"hit","evidence":"The issue leaves open where the map lives (sidecar, dispatch section, or run workspace)."},"criteria_shape":{"value":"hit","evidence":"Five acceptance criteria; two are evidence over future transcripts and one is a human judgment."}},"paths":["home/common/agent-skills/skills/design/SKILL.md","home/common/agent-skills/skills/design/evals/evals.json","home/common/agent-skills/skills/writing-plans/SKILL.md","home/common/agent-skills/skills/writing-plans/evals/evals.json","home/common/agent-skills/skills/from-issue/AUTO.md","home/common/agent-skills/evals/assert-lib.sh","home/common/agent-skills/scripts/artifact_budget.py","home/common/agent-skills/artifact-budget-policy.json"]}`
Verdict: `{"hits":["contract_change","open_design_questions","criteria_shape"],"lane":"full","mode":"shadow"}`
ran: full (shadow)

The triage input predates the design: per D2 the artifact-budget checker and its policy are not touched.

## Problem

Design and planning run as separate agents, and only the spec passes between them. The spec's decisions are deliberately free of file paths and line numbers, so what the design agent learned about where things live is thrown away and the planner finds it again. Across ten issues planned on 2026-10-09 and 2026-10-10, 46–90% of each planner's read calls (median about 64%) landed on files the design agent had opened in the same hour, planners ran 37–140 turns, and planning was the most expensive single agent in most issue trees. The reading that only the planner does, mostly tests and neighbouring source, is needed to write file-level tasks and is not the problem.

## Solution

The `design` skill leaves a **code map** next to its work: a short navigation file listing, for each thing the spec decides about, where it lives today. The planner reads the map before it maps files, and opens a mapped file only where a task needs the detail. The map is a hint, never an authority: it holds no decision, the planner checks what it relies on, and a missing or wrong map costs only the reading the planner does today.

The map lives in the worktree's git directory, named after its spec, and is never committed (D1). The spec stays one file and stays path-free in its decisions. The autonomous plan dispatch names the map; a planner invoked any other way finds it by the same naming rule.

## Decisions

### The code map

- **What it is.** One Markdown file with one entry per module, seam or contract that the spec's Decisions section decides about. An entry is a heading and three labelled lines:

  ```markdown
  ## <the name the spec uses for it>
  - Why: <one line: why it matters to this change>
  - Code: `<path>` (`<symbol>`, `<symbol>`); `<path>`
  - Tests: `<path>` (`<test name>`)
  ```

  A path is repository-relative and stands outside parentheses; the symbols or test names that belong to it follow in parentheses. `Tests:` may read `none read`. The first line of the file is a title naming the spec file.
- **What it never holds** (D3): a decision, requirement or rationale; a line number; a code excerpt. A fact the plan needs as a requirement belongs in the spec. Symbols are named because a name can be searched for after the file changes; a line number cannot.
- **Only what design already read** (D3). The design agent writes the map from the files it opened while grounding and interviewing. It reads nothing further to complete the map: an entry it cannot fill is left out, and a decided thing with no code today (new work) gets no entry.
- **Where it lives** (D1). In the git directory of the worktree the design ran in (what `git rev-parse --git-dir` prints there), as a file named after the spec file with `.md` replaced by `.code-map.md`. It is outside the working tree, so it is never staged, committed, pushed, reviewed or counted by any product-size gate, and it disappears with the worktree. A rerun of design on the same spec overwrites it.
- **When it is written.** After the spec's final fresh-eyes edit and before the producer report. Writing it does not touch the spec, so it voids no measurement.
- **It never changes the design's outcome** (D3). The producer report, its schema and its states are unchanged, and the report never carries the map's contents. When the map cannot be written, the design still completes and its `notes` say the map was not written.
- **Not budget-checked** (D2). The map belongs to no artifact-budget kind. It is bounded by its form: at most one entry per decided thing in a spec that is itself bounded, three lines an entry, no excerpts.
- **One name.** Skill text and docs always write "code map" in full. The workflow already has a context map, decision maps and a plan's acceptance map, so a bare "map" is ambiguous there. (This spec shortens it only where the code map is the sole subject.)
- **Later spec writers leave it alone.** The grill and the planner's ledger appends do not update the map. It may be stale by the time it is read; that is accepted by design.

### The planner

The `writing-plans` skill, before it maps the files to create or modify:

1. Looks for the spec's code map: the path its caller named, else the naming rule above applied to the spec it was given. No map is not an error; it plans as it does today. That covers requirements that are not a `design` spec, a spec written before this change, and planning in a clone other than the one design ran in.
2. Reads the map first and takes its entries as leads. It opens a mapped file only where a task needs detail the entry does not give (an exact signature, the test to extend). Reading beyond the map, for tests and neighbouring source, is expected.
3. Checks every mapped path and symbol it writes into a task against the current tree with a bounded search. A wrong entry is dropped and searched for afresh; an error copied from the map is a plan error like any other.
4. Never cites, links or copies the map into the plan. Implementers and reviewers cannot see it; each task still carries its own exact files and interfaces.

### The dispatch

- The autonomous plan dispatch of `from-issue` adds one item to what it hands the plan subagent: the code map's file name and that it sits in the worktree's git directory. The controller derives the name from the validated spec path in the design report; it runs no command and reads no file to do so (D4).
- The design dispatch is unchanged: the `design` skill writes the map as part of its own output. The inline fallback used when `design` is not installed writes no map.
- The interactive Phase 4 text is unchanged: the planner's own lookup covers it (D4).

### The evals

- **`design` gets its first eval file** (D5), with one pipeline case: run `design` autonomously on the fixture's well-specified issue, on the current branch, producing and committing only the spec. It asserts that:
  1. a spec exists under the retained specifications directory and is committed;
  2. the spec's Decisions section is path-free (the spec-format check, below);
  3. the code map exists at its location for that spec;
  4. the map is well-formed and lists the files of the modules this issue must decide about: the command-line module, the model module that enumerates the states, and the command-line test module (D6);
  5. no code map file is tracked or present in the working tree;
  6. the implementation was not started.
- **`writing-plans` gains one case** (D7): the model is told to change nothing, is given a validated design report for a named spec and worktree, and is asked to print in full the prompt it would dispatch to the plan subagent as the autonomous `from-issue` controller. It asserts that the printed prompt contains that spec's code map file name and that the repository is unchanged.
- The existing `writing-plans` pipeline case, which has no map, must still pass: it is the check that an absent map changes nothing.
- **Two helpers join the shared eval assert library:**
  - **The spec-format check** takes a spec and a repository. It fails, naming each offender, when the spec's `## Decisions` section contains the repository-relative path of a tracked file or a line reference (a file name followed by `:<number>`, a `#L<number>` anchor, or the word `line` or `lines` followed by a number). It fails when the spec has no Decisions section. Other sections are not inspected (D5).
  - **The code map check** takes a map, a repository and zero or more required paths. It fails unless the map is a file with at least one entry; every entry has a `Why:` line and a `Code:` line naming at least one path; every path on a `Code:` or `Tests:` line, read outside parentheses, is a tracked file; and every required path is listed.

### Documentation

The agent-skills README, which already records where each piece of pipeline state lives, gains the code map: its location, its lifetime, and that it is neither committed nor budgeted.

### Instruction budget (D8)

Measured headroom at the base, in bytes: design-and-grill owner hot 0; planning owner hot 0; controller hot 168; orchestrated issue owner hot 579; implementation owner hot 9; corpus 2. Only the user can grant a raise. Consequences the plan must honour:

- each edited skill document ends no larger than it started: every added byte is paid for by wording-only tightening in the same document, chosen and measured in the plan;
- no cut removes a rule, a pinned line (dispatch markers, `Agent(...)` call lines, carrier clauses, vetted shell examples, frontmatter) or a contract another skill cites;
- no skill-tree file is added outside an `evals` directory, and the load model changes at most a profile note or a ceiling lowered by `tighten`;
- if a document cannot fit both the new rule and its payment, the work stops and returns to the user. The rule is not thinned until it fits.

## Acceptance criteria

In issue order, kinds as tagged by the issue.

- **AC1 [evidence]** At most 30% of the planner's read calls touch a file the design agent opened. Measured on the design and planner transcripts of the next three orchestrated nodocom issues run with the merged skills installed, comparing file paths in read, grep and sed calls; baseline median about 64%. Pending at merge (D9).
- **AC2 [evidence]** Median planner turns across those three issues is at most 55, by request count per planner transcript; baseline median 79 over ten issues. Pending at merge (D9).
- **AC3 [code]** The design phase produces a code map and the planning dispatch names it. Measured by the new `design` case (asserts 3 and 4) and the new `writing-plans` case, each run in working-tree mode against the branch's final skill text, each with at least one `PASS` row for that revision in the committed results file. Falsified by a missing map, a map lacking any of the three required files, a listed path that is not tracked, or a printed plan prompt without the map's file name.
- **AC4 [code]** Specs remain free of file paths and line numbers. Measured by assert 2 of the new `design` case. Falsified by any tracked path or line reference in the produced spec's Decisions section.
- **AC5 [human]** Plans written from a map are no weaker than before. The maintainer compares plan-review findings on those three issues against the prior ten: no increase in findings that cite a wrong file, symbol or test. Pending at merge (D9).

## Test seams

1. **The eval assert library's helpers, as shell functions over crafted files**, driven from the existing eval-case test module the way the plan-verifiability helper already is, and run by `just agent-workflow-tests`. The spec-format check is falsified unless: a tracked path in Decisions fails; the same path only under Test seams passes; each of the three line-reference forms fails; a spec without Decisions fails. The code map check is falsified unless: a missing file, a map with no entry, an entry without `Code:`, an untracked listed path and an absent required path each fail; a symbol in parentheses is not read as a path; a valid map passes.
2. **Skill evals in working-tree mode**: the new `design` case, the new `writing-plans` case and the existing `writing-plans` pipeline case.
3. **The Instruction Budget gate**: `just agent-instruction-budget` prints `check: pass` with no raise.

No test pins a sentence of skill prose (the agent-helpers standard, rule 6).

## Out of scope

- Tooling that measures AC1 or AC2 from transcripts (D9).
- Any change to the artifact-budget checker, its policy or its kinds (D2).
- Grill behaviour: it neither reads nor updates the map.
- `sdd`, shipping and review: no later phase sees the map.
- An eval that seeds a map and grades how the planner uses it (D7).
- A record of files the design agent read and found irrelevant.
- Passing the map to the planner's bounded explorer lookups.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The map lives in the worktree's git directory, named after its spec, and is never committed (carryover 1). | The grounding cache already lives there, per worktree and uncommitted. The artifact-budget design (its D10) requires every committed process artifact to be excluded by hand from product-size gates, and `sdd` and shipping are out of scope. Lifecycle retries reuse the predecessor's worktree. The issue lists the run workspace as an option. | A committed sidecar beside the spec: ships one stale, path-bearing file per issue, counts as a product file until two more skills exclude it, and sorts ahead of the spec where evals take the first file. A section carried by the dispatch: the controller holds only reports, notes are capped at 500 characters, and artifacts pass as paths. |
| D2 | The map is not budget-checked and no artifact-budget kind is added; its form bounds it (carryover 2). | The artifact-budget design leaves non-delivery documents unbudgeted; the map never ships or enters a report. Working-tree evals use the deployed checker, so a new kind could not be measured on the branch. YAGNI. | A new one-file kind: checker, policy and tests for a file that is read once; revisit if maps on the three evidence issues prove large. Checking it as a `handoff`: ties two unrelated limits together. |
| D3 | The map records only what design already read, names symbols and never line numbers, holds no decision, and can never fail or change a design's outcome; an absent map means the planner works as today. | The issue: a navigation aid, not a decision record, allowed to go stale, verified by the planner. The spec's ledger is the only rationale store. Truthful terminal states: `notes` say when it was not written. | Exploring to complete the map: moves the planner's cost into design. Line numbers: wrong after the first edit. Failing design on an unwritable map: a hint is not a deliverable. |
| D4 | Only the autonomous plan dispatch changes, and it names the map by file name plus "the worktree's git directory"; the planner resolves it. The interactive Phase 4 text and the design dispatch are untouched. | Token economy: a short relative form, and no controller command. The planner's own lookup covers every other caller, so the rule has one consumer-side home. Controller and implementation-owner headroom is 168 and 9 bytes. | An absolute path: needs a controller command for no gain. Editing the interactive phase text as well: a second copy of the rule in the tightest ceiling set. |
| D5 | `design` gets its first eval file, and the spec-format check the issue calls "existing" is created there, scoped to the Decisions section and defined on tracked paths and line references (carryover 3). | No design evals exist at the base. The `design` skill scopes its no-paths rule to Decisions, and Test seams names prior art. Tests that can fail for one reason. | A whole-spec ban: fails on a legitimate prior-art mention. A "looks like a path" pattern: fails on prose such as slashed alternatives. |
| D6 | Coverage is asserted with fixture knowledge (the files of the modules the fixture issue must decide about) plus structural validity. | A spec's Decisions section has no machine-readable list of modules, and the issue's criterion needs "an entry per decision that names a module" to be checkable. | Joining map headings to spec text verbatim: fails on wording, not on missing coverage. Requiring structured Decisions headings: changes the spec format and costs prose the budget does not have. |
| D7 | The "brief carries the path" check is a `writing-plans` case that asks for the autonomous plan prompt and greps the transcript; no case seeds a map to grade its use. | The issue names the `writing-plans` evals. Subagent prompts are not observable in an eval sandbox; the root transcript is. The agent-helpers standard forbids a unit test that pins a phrase. Setup kinds are a closed set of four. Use is measured by AC1, AC2 and AC5. | A fifth clause in the dispatch-contract suite: that suite holds the leaf-agent clauses only. A pipeline run through Phase 5: far costlier and the brief is still unseen. A new setup kind for a seeded map: runner work for a behaviour the evidence criteria already measure. |
| D8 | The change is byte-neutral per edited skill document with no raise and no new skill-tree file outside `evals`; it stops rather than thin the rule. | Headroom measured at the base; the raise label is the user's alone; the same route was taken for issues 351 and 352. | Asking for a raise: outside this run's authority. A reference file read on demand: needs a load-model entry, which needs the label. |
| D9 | AC1, AC2 and AC5 are post-delivery evidence, pending at merge, and no transcript-measurement tooling is built (carryover 4). | Each is defined over three future orchestrated issues; the shipping phase holds an issue for verification, as it did for issues 351 and 352. | Building a transcript analyser now: unrequested, and the issue states how the maintainer measures. |
| D10 | Amends D8's "wording-only": each document pays by cutting sentences that it or a hot-set sibling already states, parenthetical examples, decision-ID citations and one tool-owned clause, never a rule or a test-pinned string. The design-side rule is compressed, with the README as its long form. In `writing-plans` the existing bare "the map" becomes "the file map". Prototype at the base: `design` −4 bytes, `writing-plans` −18, the autonomous-mode file −26. | D8's own limits (no rule, pin or cited contract is cut); issue 352's D7, D9 and D10 took the same route. The contract tests pin the report's state list, its four metric names and the first member path, so those stay. Grill and planning each carry their own remeasure rule. | Rewording alone: measured at about 390 of the 800 bytes `design` needs. Stopping for a raise: no rule is cut, so D8's stop condition is not met. |
| D11 | Eval shape: the `design` case has exactly the six asserts listed above, and the two that need the code map derive its path inline. In a code map a path is a backticked token outside balanced parentheses. A line reference's file name needs an extension that starts with a letter. The new cases' asserts are unit-tested over a crafted sandbox. AC3's "PASS row for that revision" is a tree-mode row from a clean tree whose instruction paths equal the final head's, with at most three runs a case. | AC3 and AC4 cite the asserts by number. Symbols are often written with call parentheses. A host and port is not a file reference. Issue 331 tested case asserts this way and measured a tree-mode row. | A third helper for the path: the spec adds two. Stripping parentheses with one pattern: breaks on call parentheses. Rerunning until green: hides a real failure. |
