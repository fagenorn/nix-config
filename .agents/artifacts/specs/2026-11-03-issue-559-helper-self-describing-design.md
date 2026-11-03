# Lifecycle inputs from installed material: a forecast generator, field-named ship-summary refusals, no skill pointers into `python/` — issue 559

Issue: https://github.com/fagenorn/nix-config/issues/559. Base `5dfe65ef` (`origin/main`).
Designed autonomously (`from-issue --auto`); every call made without the user is a row in
the Decision ledger, which this spec owns.

## Triage

Input: contract_change=hit (new subcommand, refusal messages), concurrency_or_persistence=no, open_design_questions=hit (generator input shape), criteria_shape=hit (criterion 4 not code-checkable); paths: python/agent_tools/review_feasibility.py, python/agent_tools/review_forecast_writer.py, home/common/agent-skills/scripts/artifact_budget.py, home/common/agent-skills/skills/writing-plans/SKILL.md, home/common/agent-skills/skills/sdd/SKILL.md, home/common/agent-skills/skills/retro/SKILL.md, tests/test_review_feasibility.py, tests/test_artifact_budget.py, tests/test_skill_sections.py, python/README.md. Verdict: `{"hits":["contract_change","open_design_questions","criteria_shape"],"lane":"full","mode":"shadow"}`. ran: full (shadow)

The triage paths name `tests/test_artifact_budget.py` and `tests/test_skill_sections.py`. The
first does not exist and the second tests the `skill-sections` command, so neither is a seam
here. The seams this design uses are under Test seams (D7, D8).

## Problem

Lifecycle owners learn the helper CLIs by reading their source. Over 216 jarbird owner
transcripts, 822 Bash calls read helper source in the Nix store, in `~/.agents/lib/python` or
under a nix-config clone's `python/agent_tools/`. Two cases from the issue:

- **Plan phase.** `writing-plans` § Review feasibility forecast tells the planner to hand-write
  the `## Review feasibility delivery` and `## Review feasibility task` JSON blocks, and it
  sends the planner to nix-config's `python/README.md` for the field meanings. That file is not
  installed. The planner read four `review_*.py` modules, wrote a throwaway generator and took
  three edit-commit rounds before the gate accepted the blocks.
- **Ship phase.** `ship-delivery summary` refused with `invalid ship summary`. The owner read
  `artifact_budget.py` to find which rule had failed. On base that message still covers four
  different rules (`issue`, `discussion_items`, `issue_closed` and the detail-field pairing),
  and `invalid ship summary state` covers six. Issue 472 already names the notes bound and the
  key set, but not these.

Three installed skill files point into nix-config's `python/` tree: `writing-plans` (§ Review
feasibility forecast), `sdd` (§ Cumulative delivery gate) and `retro` (§ Files).

## Solution

`review-feasibility` gains a `forecast` subcommand. It takes the plan root, the delivery base,
the spec and a small estimate document written by the planner. From these it writes the
canonical forecast blocks into the root and every task member (D1–D5). `writing-plans` tells
the planner to run it, and the subcommand's `--help` carries the input shape and the sizing
rule. The planner needs no field semantics any more (D9).

The two composite ship-summary refusals keep their class and their message as a prefix. Each
one now goes on to name the member and the rule it broke. The shared detail-field check does
the same for its other caller, the SDD report (D6, D7).

No skill file names a path under nix-config's `python/` tree. A new `skill-lint` rule, L6,
enforces this over every Markdown file in the three skill trees (D8, D9). AC4 is post-merge
evidence (D11).

## Decisions

### `review-feasibility forecast` — argv and input (D1)

```
review-feasibility forecast --plan P --base B --spec S --input FILE|-
```

- `--plan` is the plan root. Its members are the ones `artifact-budget check --kind
  implementation-plan` discovers. The gate's loader uses the same discovery, so task `N` is
  `<stem>.tasks/task-N.md` for N = 1..count.
- `--base` is the full 40-hex delivery base, the value later passed to `gate --base`. It must
  name a commit.
- `--spec` is the design spec the plan serves. It is recorded as the root's
  `process_package.spec`, repository-relative.
- `--input` is the estimate: one closed JSON object, read from a file or from stdin under the
  review-package report wire bound, the way `confirm` reads its input. The JSON load is strict
  and refuses duplicate keys and non-finite literals.

The estimate has this shape:

```json
{"tasks":[{"files":[{"path":"src/a.py","change":"add","added_lines":120},{"path":"src/b.py","change":"modify","added_lines":30,"deleted_lines":10},{"path":"old.py","change":"delete"}]}]}
```

- `tasks` has exactly one entry per member, in task order. `files` may be empty, for example in
  a task that only runs verification.
- Each `files` entry has a closed key set that depends on its change. An `add` has `path`,
  `change` and `added_lines`. A `modify` adds `deleted_lines` to those. A `delete` has only
  `path` and `change`. Line counts are integers ≥ 0. A path appears at most once in a task.
- `path` follows the forecast's path-safety rules. It is never the spec, the root or a member,
  because the generator forecasts those itself.
- The path state is walked task by task from the base tree. An `add` needs the path absent:
  absent at the base, or deleted by an earlier task. A `modify` or a `delete` needs the path
  present: present at the base or added earlier, and not deleted since. A base entry that is
  not a blob is refused.
- The estimate is never stored. A rerun takes a complete fresh estimate; the written task
  blocks show each record's path, change and cumulative line counts.

### Emitted blocks (D3, D4)

Every value is a function of the plan bytes, the base, the spec and the estimate.

- **Delivery block.** `schema_version` 3 and its `kind`. `delivery_base` is B and
  `proposed_boundary` is `all`. There is one boundary `all`:
  - `parent` null, `tasks` 1..N and a fixed non-empty `acceptance`;
  - `depends_on` [] and the `delivery-base` prerequisite;
  - `process_package` {spec, plan, tasks} and `process_forecast_ids` `s`, `p`, `t1`..`tN`;
  - N + 4 `process_commit_subject_bytes` entries of 64.

  The block also holds the process records and `derived_from: null`. Its `actual_evidence` is
  `git-range-ownership/v1` with `head` B, B's tree and `process_ranges` [].
- **Task block** for task N. `schema_version` 3 and its `kind`, then `task`:
  - `id` N, `commit_subject_bytes` [64, 64, 64] and `actual_ranges` [];
  - one record per estimate entry, in input order.

  A record has `id` `r<N>-<k>` (k counts from 1 in input order), `owner` N, `path`, `change`,
  and `last_task`: the last task whose estimate names the path. Its single bound is for `all`,
  and that bound's `authored-cumulative/v1` support covers that path's record ids so far.

### The estimate rule (D2)

These constants have one home, the generator module, and `--help` prints them.

- **Product records.** Record k on path P gets `record_bytes` = 2,560 + the sum of P's charges
  through record k.
  - An `add` or `modify` charges 128 × (`added_lines` + `deleted_lines`).
  - A `delete` charges the base blob's bytes plus its line count when P is present at the base
    and was not deleted earlier. Otherwise it charges 0.

  `added_lines` and `deleted_lines` are the cumulative sums. A `delete` adds the base line
  count to `deleted_lines` when it is charged.
- **Process records** `s`, `p` and `t<N>`. The change is `add` when the file is absent at the
  base and `modify` otherwise.
  - `record_bytes` = 2,560 + the file's bytes + its line count + 4,096 + 256 × N. The bytes are
    measured as written: the root and each member include their own new block.
  - `added_lines` is the line count plus the allowance at 64 bytes a line, rounded up.
    `deleted_lines` is 0 and `last_task` is N.
  - The 4,096 bytes cover later Phase-5 and ledger edits. The 256 bytes per task cover the
    range entries that `sdd-gate record` adds.

The forecast is a planning estimate. Completed work is always measured as it actually is, and
the cumulative delivery gate catches an underestimate during delivery.

### Writing and refusals (D5, D12)

- All values are computed before any file is written. The objects are checked first with the
  validators the gate's loader applies to boundaries and records, so a generator bug is a
  refusal, never a bad block.
- A section whose heading appears once is replaced. Its extent is the parser's own: from the
  heading to the next line that starts with `## `. An absent section is appended at the end of
  the file. A heading that appears twice is refused.
- Each changed file is replaced atomically, and a file whose bytes would not change is left
  alone. A rerun with the same inputs is byte-identical.
- An existing block that parses and carries recorded evidence (a non-empty `actual_ranges` or
  `process_ranges`) is refused. From the first recording, `sdd-gate record` owns the blocks.
- The generator commits nothing.
- When member discovery fails, the refusal carries the checker's own one-line reason (issue
  472's value-free form), such as `invalid task index row`. The budget authority's `check`
  appends that line to its `budget check failed` error, so `project`, `gate` and `sdd-gate`
  details gain it too (D12).
- **Exit 0** prints one canonical JSON line, `{"written":[...]}`: the repository-relative paths
  whose bytes changed, the root first and then the members. An empty list means nothing
  changed.
- **Every refusal** follows the command's existing contract: exit 2, empty stdout and one
  stderr line `review-feasibility: <reason>`. An input reason names the member in wire
  spelling, such as `tasks[1].files[0].change`, plus the rule it broke. It never echoes an
  input value.

### Ship-summary refusal reasons (D6, D7)

`validate_ship_summary_report` keeps the order it has today: key set, notes, then the field and
state rules. It raises at the first failure, so one input always gives the same line. Each
message keeps its old text as a prefix and adds `: <member> <rule>`, and names the state when
the rule depends on it. The CLI line stays `artifact-budget: invalid report: <reason>`, with
exit 2 and empty stdout (issue 472 D1).

| Rule | Reason (wording not normative) |
|---|---|
| `issue` | `invalid ship summary: issue must be a positive integer` |
| `discussion_items` | `invalid ship summary: discussion_items must be an empty list` |
| `issue_closed` | `invalid ship summary: issue_closed must be a boolean` |
| detail pairing | `invalid ship summary: report_path must be cited in notes when detail_state is present` |
| `pr_url` (was `invalid PR URL`) | `invalid ship summary: pr_url must be null or a non-empty string` |
| state, merged | `invalid ship summary state: merge_sha must be a 40-hex commit when state is merged` |
| state, stopped/failed | `invalid ship summary state: issue_closed must be false when state is stopped` |
| unknown state | `invalid ship summary state: state must be merged, stopped or failed` |

- The shared detail check returns the failing reason, not a boolean. It names `detail_state`
  outside its closed set, and `report_path` when that is not null for `none`, not a durable
  delivery-home path for `present`, not a retained path for `unpublished`, or not cited in
  `notes`. The SDD report, its other caller, raises `invalid SDD report: <reason>`.
- The v2 `ship-summary` boundary, which is the `ship-delivery summary` path, wraps the same
  rule. Its line becomes `…: ship-summary: invalid ship summary: <member> <rule>`, and
  `ship-delivery` relays it unchanged. `ship-delivery` itself does not change.
- The notes bound has been named since issue 472 (`notes has N characters; the bound is M`).
  AC2's test pins it alongside the new reasons.

### Skill text, the L6 rule and docs (D8, D9, D10)

- **writing-plans § Review feasibility forecast** becomes the generator call, a one-line
  estimate example and two rules: rerun the generator after any edit that changes a task's
  files, and a refusal names the failing field. The generator runs after the content is final
  and before § Package budget, with `<base>` pinned there. A § Projection gate correction round
  fixes the estimate or the plan and reruns the generator. The file may grow by at most 71
  bytes: the no-growth contract test (#227) allows that much, inside the planning-owner's 89
  bytes of Instruction Budget headroom. The writing-plans machine-text pins in the skill
  contract tests drop `git-range-ownership/v1` and `authored-cumulative/v1`, which the skill no
  longer tells anyone to write, and gain the `forecast` argv (agent-helpers rule 6). The block
  headings stay pinned.
- **sdd § Cumulative delivery gate** drops its parenthetical pointer. `sdd-gate`'s refusal
  already names its `step` and `detail`.
- **retro § Files, Helpers** names nix-config's command table, `lib/agent-tools.nix`, instead
  of `python/agent_tools/`.
- **The Phase-5 documents** (`from-issue` standards-review and REVIEW-CONTRACT) stay unchanged
  (D10).
- **skill-lint L6.** It applies to every `.md` file under the three skill trees, `evals/` and
  `scripts/` included, because whole skill directories are installed. It reports a token
  `python/` that does not follow a path character, which covers `python/README.md`, and every
  `agent_tools/`. The installed `~/.agents/lib/python/…` paths therefore stay legal. The
  live-tree-clean test makes it a check.
- **python/README.md** § Review packaging and feasibility gains the `forecast` contract: argv,
  the estimate shape, the rule constants, writing and refusals. The forecast field-semantics
  paragraph stays as the maintainers' contract.
- Every skill edit passes `just agent-instruction-budget` with no raise. Only the user applies
  the `instruction-budget-raise` label.

## Test seams

Each seam follows prior art in its suite.

1. **The `review-feasibility` CLI** over a real-Git fixture, run as `python -m
   agent_tools.review_feasibility` with `SourceProjectionFixture`'s fixture home and `PATH`
   (`tests/test_review_feasibility.py`).
   - **AC1.** A fixture plan with dependent tasks. Task 1 adds a file and modifies a base file.
     Task 2 modifies task 1's file and deletes a base file. Run `forecast`, commit, then
     `gate --completed-through 0`: exit 0, `state` `complete`.
   - A rerun prints `{"written":[]}` and leaves the bytes identical.
   - Each process bound is at least the written file's whole-record add size.
   - A refusal table covers count mismatch, change versus path state, unknown key, process path
     and duplicate heading. Each case gives exit 2, empty stdout, the member path in the reason
     and no file changed. A broken Task index row gives the checker's reason (D12).
   - Blocks with recorded evidence are refused.
2. **The `artifact-budget validate-report` CLI**, through `run_validate` and `assert_refusal`
   (`home/common/agent-skills/tests/test_artifact_budget.py`).
   - **AC2.** A table over every ship-summary rule asserts the member and its bound or rule.
     It includes an over-long-notes row that asserts `notes` and the policy bound, and the same
     rows on the v2 `ship-summary` boundary.
   - An SDD report detail row.
3. **`skill_lint.lint`** over fixture snapshots
   (`home/common/agent-skills/tests/test_skill_lint.py`).
   - L6 reports `python/README.md` and `agent_tools/`, including in an `evals/` file, and
     leaves `~/.agents/lib/python/` alone.
   - **AC3.** `test_the_live_tree_lints_clean` runs L6 against the live tree.
4. **The skill contract tests** (`test_workflow_skill_contracts.py`):
   `ProjectionCallerContractsTest` with the swapped pins, and the no-growth tests for
   writing-plans and sdd. **The Instruction Budget gate**, `just agent-instruction-budget`, also
   passes on the branch.

AC4 (`[evidence]`) cannot be graded at merge. It is pending post-merge evidence: over the next
10 orchestrated issues, owner Bash calls matching `nix/store|agent_tools|\.agents/lib/python`
must be ≤ 1 per issue. The ship flow's acceptance handling decides whether to close or hold
the issue (D11).

## Out of scope

- Child boundaries in generated forecasts, and every other change to forecast schema v3,
  `project`, `gate`, `confirm` or `sdd-gate record` (D4).
- Sharpening other refusals, each named here:
  - ship-handoff (`invalid lifecycle identity`, `scalars`, `report path`, `state`);
  - `invalid SDD state` and `invalid ledger result`;
  - `review-package`;
  - `ship-delivery`'s own messages;
  - `review-feasibility`'s loader refusals (D6).
- Parsing task `Files:` prose, and committing or storing the estimate (D1).
- Phase-5 skill text: `from-issue` standards-review and REVIEW-CONTRACT (D10).
- Installing `python/README.md` or a new share document, and adding skill reference files (D9).
- Transcript-measurement tooling for AC4 (D11).

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The generator takes `--plan --base --spec --input`. The input is a planner-written closed estimate JSON, never committed: per task and per path, the change plus line counts. The change is explicit, so it is cross-checked against the path state | Phase-0 open Q1. Forecast field names reused. The bar's token economy. Explicit change mirrors `Files:` Create/Modify/Delete and catches path typos | Parsing `Files:` prose: no task text is machine-read today, `Test:` lines are ambiguous, and line estimates are still needed. Inferring `change`: it loses the typo check |
| D2 | `record_bytes` = 2,560 per record + 128 per added or deleted line, cumulative per path. A delete is charged its base blob whole. The constants live in one home and are printed by `--help` | python/README.md conservative-bound rule. Hand practice (#557: 40+/24- → 8,192). Calibration over 150 merged PRs at -U10: given true line counts this covers about 93% of adds and 68% of modifies, with 10 false delivery overflows | A sound whole-file bound: 99 of 150 deliveries falsely overflow the 64 KiB member limit. A hunk-aware rule: planners cannot know the hunk count |
| D3 | Process records are measured from the files as written, plus 2,560 + 4,096 + 256 per task. Subjects are 3 × 64 per task and (N + 4) × 64 for the process. `acceptance` is a fixed text | writing-plans: sizes include recordings and the Phase-5 edit. `sdd-gate record` adds one range per task | Planner-supplied process sizes: the hand computation this issue removes |
| D4 | Only the single root boundary `all` is generated. There are no child boundaries. AC1's "dependent tasks" are same-path dependencies: a later task builds on a file an earlier task adds | 18 of 19 committed plans are root-only; the 19th is #227's own feature plan. YAGNI. A plan that overflows with no recommendation already takes the decompose path | Input-declared children: each needs a synthetic future process package and records, for a path planners almost never use |
| D5 | The generator writes in place: replace once-present sections or append, compute and self-validate everything before writing, rewrite only changed files, and refuse blocks that carry recorded evidence. Stdout is `{"written":[...]}` | Issue: "writes (or prints)". The jarbird failure was hand-pasting. `sdd-gate record` owns the blocks after the first recording. The bar's defense in depth | Print-only: the planner pastes long JSON lines by hand again. Preserving recorded evidence: it would make the generator a second owner of `record`'s data |
| D6 | Refusal breadth: the ship-summary composites (`invalid ship summary`, `invalid PR URL` folded into it, `invalid ship summary state`) name the member and the rule, keeping the old text as a prefix. The shared detail check returns a reason, so the SDD report's detail failure is named too. No other validator changes | Phase-0 disposition 3: keep it tight and extend only where the same helper change covers it naturally. Issue 472 D1–D3 sets the line format; `invalid SDD state: <fault>` is the prefix precedent | Sharpening every artifact-budget, review-package and ship-delivery composite: an unbounded scope with no reported failure |
| D7 | AC2 is a table test over every ship-summary rule on the v1 and v2 boundaries. Its over-long-notes row asserts `notes` and the bound, which issue 472 already named | AC2 as written passes on base, and the bar's tests-that-can-fail asks for a check that can fail. The jarbird failure ran through the v2 ship-delivery path | Only the notes row: it is green before the change and proves nothing new |
| D8 | AC3's check is a new `skill-lint` rule L6 over every `.md` file in the shared, Claude and Codex skill trees, `evals/` and `scripts/` included. It reports `python/` path tokens and `agent_tools/` | skill_lint already owns the skill-tree rules and has a live-tree-clean test (framework-first). Whole skill directories are installed | A standalone test in `tests/test_skill_sections.py`: that file tests the skill-sections command. Matching only the two literal strings: it leaves `python/` paths open |
| D9 | No relocated document. writing-plans carries the call and a one-line estimate example; `forecast --help` carries the shape and the rule. sdd drops its pointer, and retro names `lib/agent-tools.nix` | Phase-0 open Q4. The planning-owner has 89 bytes of Instruction Budget headroom and only the user may raise it. The generator removes the planner's need for field semantics. Help text is installed with the command | A reference file in the skill directory: an instruction-load model edit plus an L4a naming. Installing python/README.md under `~/.agents/share`: 188 KB of maintainer contracts |
| D10 | The Phase-5 documents stay unchanged. A Phase-5 forecast fix may rerun the generator, which `review-feasibility --help` lists, but no Phase-5 text sends it there | #227's no-growth test leaves standards-review 2 bytes of slack and REVIEW-CONTRACT 17. The issue names the plan phase. Today's hand edits stay possible, so nothing regresses | A rerun sentence in standards-review: it needs about 70 bytes of trims in unrelated pinned rules. A remedy clause in REVIEW-CONTRACT: it would have to drop the process-artifact and recording-subject check to fit |
| D11 | AC4 is delivered as pending post-merge evidence; the three code criteria are delivered. The ship flow's acceptance handling decides whether to close or hold the issue | Phase-0 disposition 2. AC4 measures 10 future issues | Building transcript-measurement tooling now: out of scope per Phase 0 |
| D12 | The budget authority's `check` appends the checker's one-line stderr reason to `budget check failed`. The generator's discovery refusals name their cause, and so do `project`, `gate` and `sdd-gate` | D5's refusal contract. Issue 472 makes checker reasons single-line and value-free, within the 400- and 300-character relays. No test pins the bare text | Duplicating member discovery in the generator: a second home for the checker's rules. Leaving it bare: the planner's likeliest refusal would name nothing |
| D13 | Planning: D12's text is `budget check failed: <the checker's last non-empty stderr line, whitespace collapsed, at most 200 characters>`, or `exit <n>` with no stderr. A generator shape refusal states the expected key set instead of echoing an unexpected key. L6 reports one violation per matching line, keyed `L6 <path>:<line>` | `review_gate._reason` already relays a child's last stderr line this way. D5: a reason never echoes an input value. skill-lint keys name the file a fix touches | Stripping the `artifact-budget: invalid input:` prefix: it hides which tool refused. Echoing unexpected keys as issue 472 does: a key is input too. One L6 violation per file: it hides the other hits |
| D14 | Phase 5: the generator's no-change guarantee covers validation refusals only. Step 9 replaces files one by one, each atomically, so an `OSError` on a later file can leave earlier files replaced; a rerun with the same inputs converges | Codex plan review S2: the plan's invariant overstated what sequential per-file replacement gives. D5 already makes a rerun idempotent | A multi-file transaction (staging every file, then renaming): no partial-write failure has been reported, and a rerun already repairs it (YAGNI) |
| D15 | Execution (Task 3 review): `_detail_fault` keeps the `allow_unpublished` keyword the base `_detail_fields` already had, though both callers pass `True`; its `none or present` reason stays unreachable | The task review's plan-mandated finding, self-answered under `--auto`: the parameter predates this issue (base `5dfe65ef`), and D6 limits the change to naming reasons, keeping every accepted and refused input | Dropping the parameter here: an interface cleanup outside D6's refusal-text scope that no reported failure asks for |
| D16 | Execution (Task 4), partly reversing D8: AC3's check is a live-tree test in `home/common/agent-skills/tests/test_skill_lint.py` over the same three skill trees and the same pattern, reusing `skill_lint.TREE_ROOTS` and its snapshot readers; `skill_lint.py` stays as at base, so there is no rule L6 | `skill_lint.py` is an Instruction Budget gate file (`instruction_load.GATE_FILES`): any edit fails the required `Instruction Budget` check until a human applies `instruction-budget-raise`, which no agent may do. The test keeps D8's tree coverage and live-tree locality | L6 in `skill_lint.py` as planned: the merge would wait on a human label for a rule that changes no measurement. A new test module: the plan forecasts no such path |
