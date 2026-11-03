# ship-issue re-observes agent-checkable acceptance rows before holding — issue 478

Issue: https://github.com/fagenorn/nix-config/issues/478. This was designed autonomously
(`from-issue --auto`), so every call made without the user is a row in the Decision ledger.

## Triage

Input: {"signals": {"contract_change": {"value": "hit", "evidence": "ship-issue's acceptance contract changes: ship re-observes agent-checkable rows and recomputes acceptance_state before close-or-hold; likely a new helper CLI interface"}, "concurrency_or_persistence": {"value": "no", "evidence": "rewrites a committed acceptance record file; no ledger, lock or concurrent state touched"}, "open_design_questions": {"value": "hit", "evidence": "where the re-observation/recompute logic lives (new helper vs ship-delivery compiler vs prose-only) and how rows are classified agent-checkable is open"}, "criteria_shape": {"value": "no", "evidence": "four acceptance criteria, each measured by a named test module or just recipe"}}, "paths": ["home/common/agent-skills/skills/ship-issue/SKILL.md", "home/common/agent-skills/skills/ship-issue/REMAINDER.md", "home/common/agent-skills/tests/test_ship_delivery.py", "home/common/agent-skills/tests/test_workflow_skill_contracts.py", "python/agent_tools/acceptance_record.py", "python/README.md", "python/ship-delivery.md"]}
Verdict: {"hits":["contract_change","open_design_questions"],"lane":"full","mode":"shadow"}
ran: full (shadow)

## Problem

sdd's final review grades every acceptance criterion into the acceptance record and
derives `acceptance_state` from it. A `code` row measured by a CI check ("CI `Nix Eval`
green on the PR") cannot be observed then: the PR does not exist yet. So the row lands
`unverified`, the state becomes `unmet`, and ship-issue fixes that value for the whole
run. After a green merge it holds the issue open as `needs-verification` and asks the
user to confirm a check the agent watched pass minutes earlier.

This keeps happening. In #422 (AC4), #438 (AC4) and #450 (AC5) a `code` row naming the
required `Nix Eval` check shipped `unverified`, and #450 was held for that row alone.
In #436 ship even wrote the readings into the hold comment ("the record's verdicts are
unchanged; a human grades them"). In session
fc096c43 the user was asked to "Confirm CI `Nix Eval` is green": "Why would I have to
check CI?? The agent should just be able to do this." Then they had to ask for a sweep
of `needs-verification` issues.

The user wants an issue held only for what a human must judge. A row the agent can
observe itself is observed, recorded in the record, and counted.

## Solution

ship-issue gains one step, **Re-observe pending rows**, in Phase 6. It runs after the
required checks go green at the reviewed head, before any head is selected for the
merge. The owner picks each `unverified` `code` row whose only measurement not yet
cited is a required check, or a read-only command it can run there. It runs those
commands, then calls a new deterministic helper:

```
acceptance-record reobserve --record <record-path> --head <HEAD_SHA> --checks <file> --row <ACn> --ran "<command>=<exit code>"
```

`<file>` holds `gh pr checks <pr-num> --required --json name,bucket,link`. The helper
matches each named row's measurements against those observations. It rewrites the row
under sdd's own `code` rule: all observed passes make it `met`, an observed failure
makes it `unmet`. It recomputes the record's state with sdd's derivation and prints it.
That state becomes ship's effective acceptance state.

When a row changed, ship commits the record, pushes it and rewrites the PR body's
`## Acceptance` section. It then runs Phase 6 again, so the required checks are green
at the head that actually merges. Close or hold then works as today, from the
recomputed state. Only `human` rows, and rows no agent can observe at ship time, still
hold.

Demo, as the issue states it: a record whose only pending row is "[code] CI `Nix Eval`
green". The owner observes `Nix Eval` pass on the PR head. The helper rewrites the row
`met` and prints `met`. Ship commits and pushes the record, waits for CI again, merges,
and closes the issue.

## Decisions

### The `acceptance-record` command (per D1, D3, D4, D6, D10)

A new `agent_tools.acceptance_record` module, installed as the `acceptance-record`
command through the command table (agent-helpers rules 1–2). It has one verb, `reobserve`:

- `--record <path>` (required): the acceptance record, relative to the working
  directory. It must be an existing regular file, not a symlink, and its name must end
  in `.acceptance.md`.
- `--head <sha>` (required): the full 40-character lowercase SHA the observations were
  made at. Ship passes Phase 6's tip-checked `HEAD_SHA`; the launch guard keeps every
  other writer off that PR head.
- `--checks <path|->` (optional): exactly what `gh pr checks --required --json
  name,bucket,link` prints. That is a JSON array of objects with exactly the keys
  `name` (a non-empty string), `bucket` (`pass`, `fail`, `pending`, `skipping` or
  `cancel`) and `link` (a string). It is loaded strictly, with the canonical
  duplicate-key and non-finite hooks. Absent, there are no CI observations.
- `--row <ACn>` (repeatable): a row the owner judged to be pending only on what this
  call observes.
- `--ran <command>=<exit code>` (repeatable): a command the owner ran at `--head`. It
  is split at the last `=`. The command is non-empty, the exit code is a non-negative
  integer, and a command given twice is refused.

**Grammar (D6).** The record holds exactly one header row whose cells are
`AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict`.
A delimiter row follows it. Every following line that starts with `|` is a row, and
the first line that does not ends the table; text after the table is kept.

- Rows split on unescaped `|`, and each must have exactly 8 cells. `AC` is `AC<n>`
  and unique.
- `Kind` is `code`, `evidence` or `human`, optionally followed by ` (classified)`.
- `Verdict` is `met`, `met (<annotation>)`, `unmet`, `unverified` or `human_pending`.
- At least one row.

Anything else is a refusal.

**Row rules (D3, D4).**

- **Admission.** A `--row` must name a row whose kind is `code` (or `code (classified)`)
  and whose verdict is `unverified`. At least one of its measurements must match an
  observation. A measurement is a backticked span of its `Check or command` cell, with
  `\|` read as `|`. Otherwise the call is refused: an unknown or duplicate `AC`, a `human`,
  `evidence`, `met` or `unmet` row, or a row with no matching span.
- **Matching.** A span matches a check whose `name` equals it, else a `--ran` command
  equal to it.
- **Check results.** `pass` passes and `fail` fails. `pending`, `skipping` and
  `cancel` leave the span unobserved, and so does a name reported with differing
  buckets.
- **Command results.** Exit 0 passes; any other exit fails.
- **Verdict.** Any failure makes the row `unmet`. Otherwise any unobserved span leaves
  the row unchanged. Otherwise the row is `met`. Spans that match nothing are the
  owner's `--row` judgment: they are already cited in the row's `Observed` cell.
- **Rewrite.** Each changed row gets an entry per matched span, joined by `; `:
  `ship re-observed <span>: <pass|fail> at <head7>`. A check entry ends with ` <link>`
  and a command entry with ` (exit <n>)`. The entries are appended after `; ` to a prior
  `Observed` value, or replace a prior `—` or empty one.
- **Cells.** `Commit` becomes `--head` and `Verdict` the new verdict. `AC`, `Criterion`,
  `Kind`, `Check or command` and `Conditions` are unchanged. New text escapes `|` as
  `\|`.

**State.** Derived from every row after the rewrite, as sdd derives it: any `unmet` or
`unverified` gives `unmet`, then any `human_pending` gives `human_pending`, otherwise
`met`. `met (<annotation>)` counts as met.

**Output and writes.**

- Exit 0 prints one canonical JSON line, `{"acceptance_state", "changed"}`, where
  `changed` lists the rewritten `AC` ids in record order.
- The record is rewritten only when `changed` is non-empty. The new content goes to a
  temporary file in the same directory, which then atomically replaces the record.
  Every byte outside the changed rows, line endings included, is preserved.
- Exit 2 prints one diagnostic line on stderr, nothing on stdout, and leaves the record
  byte-identical. It covers every refusal above, a malformed input or a read or write
  failure.
- Calling again with no `--row` only re-derives the state.

The module is a thin shell over importable functions (parse, derive, re-observe). The
contract is documented in `python/README.md`.

### ship-issue (per D2, D5, D7, D8, D9)

- **Phase 0, Effective acceptance state.** The sentence "fixed for the run and ship
  grades nothing" becomes "fixed for the run, save Phase 6's re-observation, and ship
  grades nothing".
- **Phase 6, new paragraph "Re-observe pending rows".** It applies outside remainder
  mode, while the effective state is `unmet` and there is a record. It runs before the
  selection gate, or before a ledger-free merge. In order:
  1. **Required checks.** After the required watch exits 0, save
     `gh pr checks <pr-num> --required --json name,bucket,link` to a scratch file
     (GitHub only). A docs-only run takes Phase 6's tip check and watch here too.
  2. **Pick rows and run commands.** Pick each `unverified` `code` row that has at
     least one measurement its `Observed` cell does not cite and whose uncited
     measurements are all required checks or read-only commands. A fully cited row is
     not picked, so it still holds (D14). Run the picked rows' commands once at
     `HEAD_SHA`.
  3. **Call the helper** in the worktree, with `--row` per picked row and `--ran` per
     command. Its printed state becomes the effective state. An exit 2 keeps the
     current effective state.
  4. **Publish a changed record.** When `changed` is non-empty, even if the state is
     still `unmet`:
     - commit the record alone through `### Local commits`;
     - push through REVIEW.md's steps 4–5 (`check-launch`, push, verify, re-fix
       `HEAD_SHA`);
     - rewrite the PR body's `## Acceptance` section under Phase 4's rules for the new
       state. The table is re-copied, and `Closes #<num>` is added or dropped.
     - Then rerun Phase 6, watch included.

  The paragraph states that the helper applies sdd's `code` rule to an observation and
  grades nothing, and that only `human` rows and rows no agent can observe here still
  hold.
- **Second pass.** On the rerun the effective state is `met` or `human_pending`, so the
  step is skipped. If it is still `unmet`, no row is left to pick (rewritten rows are no
  longer `unverified`), the helper changes nothing and Phase 6 proceeds, so the loop is
  bounded at one extra wait.
- **Launch guard.** The PR body edit is a forge write before the merge, so the existing
  Launch guard rule already fences it. The record commit gets no Phase 2 rerun and no
  re-review (D8).
- **Phase 8, step 1.** "Close or hold, per Phase 0's effective acceptance state" drops
  "Phase 0's": it closes or holds on the effective state, now possibly recomputed.
- **Unchanged documents.** `DELIVERY-LOOP.md`, `REMAINDER.md`, `CI-MERGE.md`,
  `HUMAN-GATE.md`, from-issue and sdd keep their text. Phase 4 renders the effective
  value, which is Phase 0's when the PR opens and the recomputed one when Phase 6
  rewrites the body (D13); Gate 1 still renders Phase 0's value. The hold comment
  copies the rewritten PR table, and a remainder reads the rewritten PR body lines (D7).

## Test seams

All of these run under `just agent-workflow-tests` (criterion 4).

1. **`test_ship_delivery.py`: the criteria's own seam (D9).** The case drives
   `python -m agent_tools.acceptance_record reobserve` from source against a record
   written in the harness root. It then completes delivery through the real compiler,
   validator and engine. `deliver()` takes the acceptance state instead of a boolean:
   it holds exactly for `unmet` or `human_pending`, carrying that value into
   `tracker_held`. The existing hold case passes `"unmet"`.
   - **Criterion 1.** AC1 is `code met`. AC2 is `code unverified`, with
     `` `just build`; CI `Nix Eval` green on the PR `` and an `Observed` citing
     `just build`. With `Nix Eval` (and `Instruction Budget`) `pass` and `--row AC2`,
     the call prints `met` and `changed: ["AC2"]`. AC2 reads `met` with the head and the
     appended entry, and every other line is byte-identical. The delivery then closes
     through `tracker_closed`, and the finished attempt has `issue_closed: true`. The
     contrast asserts that the same record with `Nix Eval` `pending` stays `unmet` and
     unchanged: that is the hold the handoff value gives today.
   - **Criterion 2.** AC1 is a CI-pending `code` row and AC2 is a `human human_pending`
     row. `--row AC1` prints `human_pending`. `--row AC2` is refused with exit 2 and the
     record unchanged. Delivery then holds: the sealed `tracker_held` subject carries
     `label: needs-verification` and `acceptance_state: human_pending`, and the attempt
     has `issue_closed: false`.
2. **`tests/test_acceptance_record.py`: the helper's own boundary**, modelled on
   `tests/test_verified_tree.py`. It runs the command from source and is added to the
   suite's member list. It covers:
   - grammar refusals: header missing or repeated, a 9-cell row, an unknown kind or
     verdict, no rows;
   - escaped pipes, `(classified)` kinds and annotated `met`;
   - each admission refusal;
   - the bucket table and disagreeing duplicates;
   - `--ran` pass and fail, and a command containing `=`;
   - text after the table and line endings preserved;
   - no write on no change or on refusal;
   - re-derivation with no `--row`;
   - strict JSON (duplicate keys, `NaN`) and a symlinked or misnamed record.
3. **`test_workflow_skill_contracts.py` (criterion 3).** `SHIP_ISSUE_MACHINE_TEXT`
   gains two argv strings. They are the helper's
   `acceptance-record reobserve --record <record-path> --head <HEAD_SHA> --checks <file>`
   and `gh pr checks <pr-num> --required --json name,bucket,link`. One ordering case
   asserts the helper argv sits after the required watch and before Phase 7's
   `gh pr merge`. Pinning argv, never an English phrase, follows agent-helpers rule 6.
4. **Budget.** `just agent-instruction-budget` must pass with no raise (D10). Existing
   phrase and shell-example contracts stay green: the `gh` span is one plain command.

## Out of scope

- sdd: its grading rules, the record schema, the conformance prompt and
  `final-review.md`. Nothing about how sdd writes the `Check or command` cell changes.
- `evidence` rows. A threshold reading is grading, and post-merge or post-switch
  measurements (#447, #448) cannot be observed at ship.
- `human` rows and attestation, including an interactive re-attestation after a
  recomputed `human_pending`. Phase 0's attestation still runs only on the handoff
  value.
- Advisory or non-required checks. So is the "no required checks reported" route,
  which passes no `--checks`.
- GitLab CI observation: `glab` owners pass no `--checks`.
- Re-observation after selection or in a post-selection sync. Remainder mode and
  from-issue's inline fallback in `ship-handoff.md` keep their current close-or-hold.
- The delivery model, `tracker_held`, the ship-delivery compiler, ledger and wire
  schemas. A compiler-side check of holds against the record is also out (D1).
- Sweeping or re-grading issues already labelled `needs-verification`.
- Permission allow-list entries for the new command.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Re-observation is a new `agent_tools.acceptance_record` command (`acceptance-record reobserve`) that parses the record, rewrites rows and derives the state. This narrowly reverses the parent spec's D6 "no record parser": the parser is a closed grammar that refuses anything else, so no judgment enters it. | agent-helpers rules 1–2 (helpers are package modules plus a command row). Criterion 1 needs a deterministic case. Parent D6's concern was judgment-bearing parsing. | Extend the ship-delivery compiler. It compiles post-selection ledger recipes and writes nothing but `--output`. A hold-versus-record check there would strand a remainder that read a stale PR body. Prose only: the owner would hand-edit Markdown rows, the judgment-bearing parsing parent D6 rejected, and criterion 1 has no deterministic case. |
| D2 | The step runs in Phase 6 after the required watch, before the selection gate. A changed record is committed alone and pushed, even when the state stays `unmet`, so a hold links a record naming only what is truly pending. The PR body is rewritten and Phase 6 reruns once. | The issue: "records the result in the acceptance record". Parent D4: the record is the committed single home of verdicts. Branch protection needs green required checks at the merged head (CLAUDE.md). Selection follows Phase 6 (DELIVERY-LOOP). The record commit leaves the cited head `fresh` under `verified-tree fresh` (#477). | Re-observe in Phase 8, after the merge. The record on `main` cannot be amended, so it would contradict the close. Pre-PR: CI does not exist yet. Commit without a second wait: protection refuses the merge. |
| D3 | The owner picks rows with `--row`: an `unverified` `code` row whose measurements not cited in `Observed` are only required checks or read-only commands. The helper admits only such rows, needs at least one span to match an observation, and sets the verdict mechanically. | A scan of the 71 committed records found 6 pending `code` rows. The three left pending on CI (#422 AC4, #438 AC4, #450 AC5) each also name spans no ship observation can match (`just build mbp`, `git diff --quiet …`, `nixosConfigurations.anis-desktop`), so a rule requiring every span to be observed would have closed none of them. | Fully mechanical span coverage: inert on real records. The agent writing verdicts itself: grading at ship (#272 D14). |
| D4 | Observations are required checks only, from `gh pr checks --required --json name,bucket,link`: `pass`/`fail` count, and `pending`/`skipping`/`cancel` and disagreeing duplicates are unobserved. Commands come via `--ran` (exit 0 passes). `evidence` rows are never re-observed. | Rejection `ungated-agent-merges`: merge safety comes from a required status check. #436 AC4: an advisory job with `continue-on-error` is green on failure. Parent spec Out of scope: no machine threshold evaluator. The issue names `just` recipes and test commands. | Count every check: advisory greens are not evidence. Re-grade evidence thresholds: judgment, explicitly out of scope. |
| D5 | Re-observation is an observation, not a grade. Only `unverified` `code` rows change, by sdd's own `code` rule ("ran and saw pass" gives `met`, "ran and saw fail" gives `unmet`). `met`, `unmet`, `human_pending` and `evidence` rows are never touched, and `--auto` still never attests a `human` row. | #272 D14 kept ship from grading so two graders cannot disagree; filling only what sdd could not observe cannot disagree with it. Parent D8. | Let ship override any verdict, which creates two graders. |
| D6 | The grammar is closed but admits the tokens sdd and ship really write: `<kind> (classified)` and `met (<annotation>)`. `Observed` entries are appended, `Commit` becomes the head and `Conditions` is unchanged. A refusal (exit 2) writes nothing and the owner keeps the effective state, so the issue still holds. | the-bar Fail loud and Truthful terminal states. The record scan found `(classified)` kinds and annotated `met`. Appending keeps sdd's citations of the other measurements. | Exact four verdict tokens: refuses real records. Replacing `Observed`: drops the evidence for spans that matched nothing. |
| D7 | The recomputed state becomes the effective state, and the PR body's `## Acceptance` section is rewritten after the push. `REMAINDER.md` is unchanged: a remainder reads the rewritten lines and never re-observes. If a run dies between push and edit, the remainder holds, which is the safe direction. | #273 D11: the PR body is the remainder's forge-durable source. Phase 5 already writes into the PR body after creation. The ship-owner conditional budget has 2 bytes of headroom. | A remainder re-deriving from the record: a `REMAINDER.md` change over budget. Editing the body before the push: a dead run could then close on a record still `unverified`. |
| D8 | The record commit pushes through REVIEW.md's steps 4–5 with no Phase 2 rerun and no re-review. The head-to-head delta is the record alone. | Declared verification does not measure the record. Phase 5's review range excludes process artifacts. Phase 3's commits can touch any document, including test-pinned skill text; this commit touches only the record. | Rerunning Phase 2: a full local suite for one Markdown file. Re-reviewing: nothing to review. |
| D9 | Test seams: the criteria cases in `test_ship_delivery.py` drive the helper from source and finish through the real engine. `deliver()` takes the acceptance state. Helper edge cases go in a new `tests/test_acceptance_record.py`. Criterion 3 is pinned as argv plus order in `SHIP_ISSUE_MACHINE_TEXT`. | The criteria name these modules. agent-helpers rules 5–6 (commands from source; skill tests pin argv, never English). Prior art: `tests/test_verified_tree.py` and the #273 hold cases. | Grammar edge cases in `test_ship_delivery.py`: its engine setup is per test and costly. A phrase pin for criterion 3: forbidden by rule 6. |
| D10 | Prose budget. ship-issue grows by one Phase 6 paragraph and one Phase 0 clause, about 1 KB, within the 1,608-byte ship-owner hot headroom, with no raise. No other skill file changes, and the contract detail lives in `python/README.md`. | `instruction-load.json`: ship-owner conditional headroom is 2 bytes; implementation-owner hot (sdd) is 79 bytes. CLAUDE.md: command contracts go in `python/README.md`. Raising the ceiling needs the user's label. | Spread the step across `REMAINDER.md`/`CI-MERGE.md`: over the conditional ceiling. Teach sdd to mark CI-pending rows: over the sdd budget, and sdd is out of scope. |
| D11 | Refines D10: `ship-issue/SKILL.md` stays at most 500 reflowed lines. The step paragraph is at most 1,100 characters, and the docs-only sentence gains only "unless rows need re-observing". Five hard-wrapped paragraphs are joined onto single lines with no byte change: the review-routing note, the Launch guard's Guarded list, `### Local commits`, `## gh hygiene` and Phase 4's Acceptance rules. | skill-lint L2 (`REFLOW_WIDTH` 100, cap 500), which the Instruction Budget gate runs. SKILL.md measures exactly 500 at `cb1d0ad5`, and the spec's paragraph took it to 516 in the planning trial. #296 reflowed this file to fit the cap. Every test pin on the joined text is whitespace-normalized. | Move the step into a reference file: a new file needs membership edits in three `instruction-load.json` profiles, and the conditional references have 2 bytes of headroom. Cut unrelated SKILL.md content: out of scope. Raise L2: it binds every skill. |
| D12 | `acceptance-record` details the spec left open. Usage errors come from a parser whose `error` raises the refusal, so they are one stderr line, and `--help` still exits 0. `AC<n>` is `AC[1-9][0-9]*`, a delimiter cell is `:?-+:?`, and a row line must end in an unescaped pipe. Only a span observed `pass` or `fail` gets an `Observed` entry, and a check entry carries the first report's `link`. A changed row is re-rendered from its stripped cells, one space each side of every pipe, keeping its `\r`. The replacement file keeps the record's permission bits. | The spec's one-diagnostic-line and byte-preservation rules. Precedent: the `_Parser` in `review_package` and `sdd_gate`, and `verified_tree._write_atomically`. The planning trial parsed 66 of the 71 committed records; the 5 it refuses are the 2026-10-07 records with `—` verdicts and #278's unescaped pipe inside a code span. | argparse's default two-line usage error: breaks the one-line refusal. An entry for an unobserved span: it has no `pass` or `fail` to write. Re-rendering every row: breaks byte preservation. |
| D13 | ship-issue Phase 4's rule says `Acceptance state:` carries the effective value, no longer "Phase 0's effective value". The spec's "Phase 4 and Gate 1 still render Phase 0's value" is narrowed to Gate 1. | Phase 6 rewrites the PR body's `## Acceptance` "per Phase 4" after a re-observation; a rule pinned to Phase 0's value would re-render the state the helper just replaced. Before Phase 6 the effective value is Phase 0's, so the PR as opened is unchanged. | Keep "Phase 0's" and spell the recomputed state out in the Phase 6 paragraph: over its 1,100-character limit (D11). A second rendering rule for the rewrite: two rules for one section. |
| D14 | Refines D3: the owner picks only an `unverified` `code` row that has at least one measurement its `Observed` cell does not cite, all of those uncited measurements being required checks or read-only commands. A fully cited `unverified` row is not picked and still holds. The helper is unchanged. | sdd's final-review freshness rule turns a `code` row recorded `met` on a cited run `unverified` when later commits touch its surface. That row cites every measurement, so D3's wording picked it vacuously; if it also names a required check, the helper matches the check, skips the stale cited command as already cited, and makes the row `met` without a current pass. | Teach the helper to detect stale citations: it would grade the `Observed` cell, which D1 and D3 keep out of the helper. Re-run every cited command at ship: commands that are not read-only, and a measurement the record already holds. |
