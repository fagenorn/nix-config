# A full-scope, independent correctness review of CORE's 25 files — issue 259

Issue: https://github.com/fagenorn/nix-config/issues/259. This was designed autonomously
(`from-issue --auto`), so every call made without the user is a row in the Decision ledger.

## Triage

```
Input: {"signals": {"contract_change": {"value": "doubt", "evidence": "A review finding could require changing a review-tooling command contract or report schema; unknown until the review runs."}, "concurrency_or_persistence": {"value": "doubt", "evidence": "The reviewed modules publish review packages to disk and read git state; a fix may touch persisted package files."}, "open_design_questions": {"value": "no", "evidence": "The issue fixes the file set, reviewer independence, finding dispositions and demo; no design question is open."}, "criteria_shape": {"value": "hit", "evidence": "Criteria 1-3 concern a posted review record and finding dispositions that no deterministic code check verifies."}}, "paths": [python/agent_tools/review_*.py, artifact_budget.py, tests/test_review_*.py, spec + plan artifacts]}
Verdict: {"hits":["contract_change","concurrency_or_persistence","criteria_shape"],"lane":"full","mode":"shadow"}
ran: full (shadow)
```

## Problem

CORE (https://github.com/fagenorn/nix-config/issues/233) built the review packer, projector,
forecast, publication and Git modules that every later code review in this repo reads its
evidence from. It shipped in https://github.com/fagenorn/nix-config/pull/246 (merge
`93e6059a6fece769a621657c5889278b9cb9e0d7`) with a correctness review that covered "20 of 25
product files" and never said which five it skipped
(https://github.com/fagenorn/nix-config/pull/246#issuecomment-5967759004). The parent audit
of https://github.com/fagenorn/nix-config/issues/226 carries that gap as a residual its closer
must accept or keep the parent open for.

The gap has a mechanical cause. The configured correctness reviewer, `codex-collaboration`'s
`diff-review`, scopes any range with more than 20 product files down to the 20 with the most
churn. Run the same way again, it would leave five files out again. So the owner of the
parent cannot yet say that CORE's code had an independent correctness review.

## Solution

Phase 6 runs a whole-file correctness review of the 25 files, writes a committed record, acts on
each finding and posts the record on the issue. Steps, in order:

1. **Pin the tree.** `REVIEW_SHA` is the full delivery base that sdd pins. Before any dispatch the
   controller checks that none of the 25 files differs between `REVIEW_SHA` and `HEAD`. The 25
   are exactly `git diff --name-only 93e6059a^1 93e6059a` minus the paths under
   `.agents/artifacts/` (per D1).
2. **Review in five batches, in parallel.** Each batch is one fresh read-only reviewer that gets
   a module cluster with its tests (per D2):

   Files are named by basename, which is unique within the 25.

   | Batch | Files | Lines at 8c475824 |
   |---|---|---|
   | B1 pack and publish | `review_pack.py`, `review_package.py`, `review_publish.py`, `review_actual.py`, `review_git.py`, `tests/test_review_pack.py`, `agent-skills/tests/test_review_package.py` | 3,642 |
   | B2 projection and forecast | `review_projection.py`, `review_forecast.py`, `review_feasibility.py`, `review_budget.py`, `tests/test_review_feasibility.py`, `tests/test_review_projection_cases.py`, `tests/test_review_history.py` | 2,813 |
   | B3 budget helper | `artifact_budget.py`, `test_artifact_budget.py` | 3,043 |
   | B4 wiring | `lib/agent-tools.nix`, `agent-skills/default.nix`, `justfile`, `CLAUDE.md`, `tests/test_agent_tools_launchers.py` | 1,431 |
   | B5 SDD skill text | `sdd/SKILL.md`, `sdd/final-review.md`, `sdd/fix-loop.md`, `test_workflow_skill_contracts.py` | 3,868 |

3. **Check coverage.** The controller checks each batch's coverage lines against Git and sends a
   file back for review when its line is missing or wrong (per D3).
4. **Check the findings.** The controller merges duplicate findings across batches, checks every
   Critical and Important finding against `REVIEW_SHA`, and gives each finding a disposition
   (per D4, D5).
5. **Fix what fits.** An implementer fixes each finding marked for a fix here: first a regression
   test that fails, then the fix (per D6). The plan cannot know the findings in advance, so its
   fix task takes this list as its input.
6. **File the rest** as their own issues, then commit the finished record (per D5, D7).
7. **Post the record** on issue 259 and fill in acceptance rows AC1 and AC2 (per D8).
8. **Finish as usual.** This delivery's own sdd final two-axis review runs over its own diff (the
   record plus any fixes), then verification and ship. That review covers this delivery's diff.
   It does not replace the review of the 25 files.

## Decisions

### The reviewer brief (per D2)

Each reviewer gets:

- its batch's paths with the instruction to read every line of each file at `REVIEW_SHA`. The
  worktree matches that tree for these paths, as step 1 checked;
- the rubric: the "What to Check" list and the "Output Format" of sdd's correctness reviewer
  prompt, applied to whole files. That prompt's diff, manifest and scoping instructions do not
  apply. "Cross-task integration" means interfaces that one CORE module defines and another
  uses;
- the standards: the-bar, the Python stack shard, and the project's agent-helpers shard;
- `python/README.md` § Review packaging and feasibility, as the documented contract;
- the known exclusions: CR-001 to CR-003, fixed in `6cdb9b9`, and the topic of
  https://github.com/fagenorn/nix-config/issues/255 (Git attributes and diff settings that change
  the record view);
- what correctness means for prose files (skill text, `CLAUDE.md`, recipes): a defect is a claim
  that is false against the code or another binding text, or an instruction an agent cannot
  follow as written.

The brief leaves out CORE's design spec, plan and PR thread, so that the author's stated intent
does not anchor the review. A reviewer may open the CORE spec only to settle whether one
specific suspected defect contradicts the documented intent, and it names that check in its
report. Reviewers never edit, and a reviewer never fixes a finding.

### Reviewer output (per D3)

The verdict line comes first, in its bare unscoped form. The three sections Critical, Important
and Minor follow, each finding with an ID, live `path:line`, confidence and unknowns, within 400
words. Then comes one more section, `### Coverage`, with one line per file:
`<path> | <blob OID at REVIEW_SHA> | <line count> | read whole`, where the count is what
`git cat-file -p <REVIEW_SHA>:<path> | wc -l` prints, and a last line `Reviewer model: <model ID>`.
Coverage lines do not count toward the 400 words.

### Severity scale (per D4)

- **Critical** (must fix before merge): a tool reports success, a clean review, a complete
  package or a within-budget result while its input is wrong or incomplete; persisted packages or
  records get corrupted or overwritten; a trust boundary is bypassed (unvalidated input reaching a
  Git argv or a filesystem path, a followed symlink).
- **Important** (should fix): a wrong result or an unhandled error on a reachable input that still
  fails loudly; a test that cannot fail for the contract it documents; a dead branch that hides a
  defect; text that tells an agent to do something the code refuses.
- **Minor**: everything else, including style, naming, wording and unreachable inefficiency.

### Dispositions (per D5)

The set is closed. Each finding has exactly one:

| Disposition | When | Evidence column |
|---|---|---|
| `fixed` | a Critical or Important finding that meets the fix-here bar | fix commit, regression test ID, failing-first line |
| `filed` | a Critical or Important finding that misses the bar | new issue URL |
| `tracked` | a finding already covered by an open issue (the 255 topic among them) | that issue's URL |
| `rejected` | checking showed the defect does not exist at `REVIEW_SHA`, or it restates CR-001 to CR-003 and that fix's regression test passes | the check that was run and its result |
| `recorded` | Minor | — |

Finding IDs are the reviewer's IDs with the batch name in front (`B2-I1`). When two batches
report the same defect, the record gives it one row and names both IDs.

A finding is **fixed here** only if all of these hold, Critical findings first:

1. Apart from its regression test, the fix stays inside the 25 files.
2. The fix makes the code meet its documented contract without changing that contract (argv,
   exit codes, report or manifest schema, persisted package format).
3. The fix needs no instruction-budget raise.
4. The fix is at most about 150 changed lines, its test included.
5. Fewer than three findings are already marked fixed here.

### Fixes (per D6)

Each fix adds its regression test at the existing seam of the code it fixes; see Test seams. The
test is run against the product code before the fix, and the run must exit non-zero on the
assertion that pins the defect, not on a missing name or import. The record
stores the first failure line beside the fix commit and the test ID.

### The record (per D7)

The record is committed at
`.agents/artifacts/specs/2026-11-01-issue-259-core-correctness-review-record.md`, under
`# CORE correctness review record — issue 259`. Its parts, in order:

1. A header naming the issue, the subject (PR 246 and its merge SHA), `REVIEW_SHA` in full and
   `Scope: full — 25 of 25 product files, each read whole`.
2. `## Reviewer`: the agent type, the model and effort, every reviewer session ID, and the
   independence statement. That statement gives the trailer tally from
   `git log --no-merges --format='%(trailers:key=Co-Authored-By,valueonly)' 93e6059a^1..93e6059a^2`
   (13 Codex, 1 Claude Opus 5.5, which is `6cdb9b9`, the shipping session's fix). The reviewer
   is a different model family from Codex and a fresh session with none of PR 246's context.
3. `## Coverage`: `| # | Path | Blob | Lines | Read | Batch | Verdict |`, 25 rows in `git diff`
   order. `Read` is `whole`. `Verdict` is `clean` or the file's finding IDs.
4. `## Findings`: `| ID | Severity | Location | Defect | Disposition | Evidence |`, one row per
   finding, Minor and rejected findings included, or `None.`.
5. `## Verification`: the commands run at the final head and what each printed.

Follow-up issues use the to-issues body template. Like 255, each one states that the defect is
CORE scope (233, PR 246), names its 259 finding ID and carries `agent:ready`. Before filing, the
controller searches the open issues. A match becomes `tracked` instead.

### The demo comment (per D8)

The controller posts one comment on 259 once every Critical and Important disposition is final
and the record is committed. That comes before sdd's final review grades acceptance. The
comment's first line is
`Correctness review record — CORE (PR 246), scope full: 25 of 25 product files`. Below it come the
record's Reviewer, Coverage and Findings sections, then the record's path and the commit they
were copied from.

AC1 and AC2 are `evidence` rows that cite the comment URL. AC1's check compares the coverage
paths in the comment with the 25 paths from Git, and the result must be an empty difference with
every row read `whole`. If a later step changes the record, the controller edits that same
comment to match. If the owner has no authority to comment on the tracker, AC1 and AC2 are
`unmet`: the record stays committed and ship holds the issue for verification.

### Grill refinements

- **Findings stay inside the 25.** Every finding is anchored in one of the 25 files. A reviewer
  may cite any other file as evidence, but a defect that lies wholly outside the 25 is not part of
  this review. This is `diff-review`'s rule for scoped reviews. Per D1.
- **Failing first means failing on the defect.** A new test that fails before the fix only because
  it imports a name the fix adds proves nothing. Per D6.
- **The coverage count is Git's.** Reviewer and controller run the same command, so a missing
  trailing newline cannot cause a false mismatch. The line pins which blob was reviewed. That the
  file was read whole is still the reviewer's own statement (D3 rejects auditing transcripts).
- **The comment's commit link outlives the branch.** The VCS binding merges and does not squash,
  so the branch commit that the comment names becomes reachable from `main`. Per D8.
- **No glossary or ADR change.** No context or decision-record path is bound
  (`knowledge.context` unsupported), and every decision here is easy to reverse.

## Test seams

- **Regression tests for fixed findings** sit at the seam the fixed code already uses:
  - for the review modules, CORE's own subprocess seam: `python -m agent_tools.<module>` under
    the recipe `PYTHONPATH`, against real temporary Git repositories, in `tests/test_review_*.py`
    and `test_review_package.py`;
  - `test_artifact_budget.py` for the budget helper;
  - `test_agent_tools_launchers.py` for installed launchers;
  - for skill text, only text that a tool or subagent consumes (agent-helpers rules 5 and 6).

  There is no new harness and no mocked Git.
- **The record and the comment** are checked with `evidence` commands, not with a committed test
  (per D8).
- **Verification bindings**: `just agent-workflow-tests` and `just build` run at the final head
  (AC4). `just agent-instruction-budget` also runs when a fix touches text the instruction budget
  measures.

## Out of scope

- Reopening CR-001 to CR-003, or the Git attributes and diff settings finding that 255 tracks.
- Fixing Minor findings. They are recorded only.
- Fixing a Critical or Important finding that misses the fix-here bar. It is filed instead.
- Redesigning the review tooling, or changing `diff-review`'s 20-file scoping.
- PR 246's four spec and plan artifacts, and every file outside the 25.
- Re-reviewing the 25 files if `main` changes them after `REVIEW_SHA`.
- Closing parent 226, which is its closer's call.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Every one of the 25 files is reviewed whole at one pinned tree, `REVIEW_SHA` (sdd's full delivery base), before any fix commit. "Scope full" means 25 of 25 files, each read whole. The record names its tree, and later changes on `main` are not re-reviewed. Findings are anchored in the 25, and other files are only evidence. | The issue: "every product file … as it stands on the default branch" and "record which files were read, so the scope is no longer a count". `diff-review`'s `full`/`scoped` vocabulary. | Reviewing only CORE's regions traced forward: in the shared files CORE changed 2–45 lines, and those files have been edited up to 173 times since, so locating those regions is a judgment that brings an unmeasured scope back. Reviewing PR 246's diff: that is not the code as it stands. A delta re-review at ship: open-ended, and later changes get their own deliveries' reviews. |
| D2 | The reviewers are five fresh read-only `reviewer` subagents (Claude Opus, effort high, the existing native correctness path), dispatched by type, one per cluster batch of at most about 4k lines. The brief leaves out CORE's spec, plan and PR thread. | The issue: the reviewer "must not be the author of the CORE code". PR 246's trailers: Codex on 13 of 14 non-merge commits, Claude Opus 5.5 on `6cdb9b9` from the shipping session. `diff-review` scopes any range over 20 files. | Codex through the configured `review.code`: Codex wrote CORE, and its 20-file bound is how the gap arose. Codex and Claude both: double the cost, and the Codex half is not independent. One reviewer for 14.8k lines: the read becomes unreliable. |
| D3 | Each reviewer returns a `### Coverage` line per file (path, blob OID, line count, `read whole`). The controller checks the path set, the OIDs and the counts against Git. A missing or wrong line sends that file once to a fresh reviewer, and a second miss fails the attempt. | AC1: "names every one of the 25 … as read". The bar: Verify before claiming done; Truthful terminal states. | Rebuilding Read calls from subagent transcripts: the on-disk layout is undocumented and not a contract. A bare scope count: that is the defect this issue fixes. |
| D4 | The severity scale is the repo's Critical, Important and Minor (must fix, should fix, nice to have), with calibration for review tooling: silent false success, persisted corruption and a trust-boundary bypass are Critical. The controller checks every Critical and Important finding at `REVIEW_SHA`. It rejects a finding only on evidence that the defect does not exist, and never changes a severity. | `diff-review`'s output contract. sdd's fix wave: "verify each finding against the live worktree first". The bar: Truthful terminal states. | Letting the controller downgrade: AC3 could then be met by relabelling. Leaving severity uncalibrated: five reviewers would grade the same kind of defect differently. |
| D5 | The dispositions are a closed set: `fixed`, `filed`, `tracked`, `rejected` and `recorded` (Minor only). Only a finding that meets the fix-here bar is fixed here: apart from its regression test it stays in the 25 files, meets the documented contract without changing it, needs no budget raise, is at most about 150 lines, and at most three findings are fixed, Critical first. Restatements of CR-001 to CR-003 are rejected after their regression tests pass. The 255 topic is `tracked`. | The issue: fix, "or file it as its own issue when the fix does not fit here"; Minor is out of scope; the 240-minute attempt budget; only the user applies the budget-raise label; the bar's fail-loud rule for closed sets. | Fixing everything found: unbounded inside the budget, and contract changes need their own design. Filing everything: the issue asks for fixes where they fit. Fixing Minors: out of scope. |
| D6 | A fixed finding's regression test sits at the fixed code's existing seam. Failing-first evidence is a run of the new test against the code before the fix that exits non-zero on the defect's assertion, and the record stores its first failure line beside the fix commit and the test ID. | AC3: a regression case "that fails before the fix". The bar: Tests that can fail. agent-helpers rule 5. | A test shown only to pass after the fix: it does not prove the test can fail. A new review-tooling harness or mocked Git: CORE's own temporary-repository seam already exists. |
| D7 | The durable record is one committed file, `.agents/artifacts/specs/2026-11-01-issue-259-core-correctness-review-record.md`, with a header, Reviewer, Coverage (25 rows), Findings and Verification. Follow-ups use the to-issues template, follow 255's shape, carry `agent:ready`, and are filed only after a search of the open issues. | Records already live in the specs dir (the 226 parent audit, the harness backlog audit). `diff-scope` excludes that dir from product files. The delivery ends in a merged PR. https://github.com/fagenorn/nix-config/issues/255 is the follow-up precedent. | The issue comment alone: not durable, and not reviewable in the PR. A new artifacts directory: no binding names one. sdd's `.acceptance.md`: sdd owns its schema. |
| D8 | The controller posts one demo comment on 259 that copies the record's Reviewer, Coverage and Findings sections, after the dispositions are final and before sdd grades acceptance. Later record changes edit that same comment. AC1 and AC2 are `evidence` rows that cite its URL, and AC1 is measured as an empty difference against Git's 25 paths. No committed test pins the record. | The issue's Demo, and AC1: "posted on this issue". The design for https://github.com/fagenorn/nix-config/issues/149 posted its evidence comment as a delivery step. sdd: a `met` evidence row needs an observed value and a threshold. | Posting after merge: `Closes` would auto-close the issue first, and AC1 could not be graded before ship, which forces a hold. A new comment per change: leaves stale duplicates. A permanent test of a one-time record: no future code can break it. |
| D9 | Refines D5. The spec's "controller" is each task's sdd implementer: Task 1's dispatches the five reviewers itself (no subagent launch is BLOCKED, never a self-review), checks coverage and findings, searches the open issues once for `tracked`, and commits the record, the only carrier between tasks via the tokens `fix pending` and `issue pending (bar <k>)`. Duplicates merge at the higher severity. Bar 4 is measured as `git diff --numstat` ≤ 150 over the fix commit, and a sixth bar item needs a regression test at an agreed seam (a weak test through a mutant run; prose only where a tool or subagent consumes it). A fix that misses the bar in Task 2 is filed, and no other finding takes its slot. | sdd: one fresh implementer per task; its controller never fixes. from-issue: sdd's writing agents may write to the forge. D5, D6, agent-helpers rule 6, AC3's "fails before the fix", the 240-minute attempt budget. | The Phase-6 owner reviewing inline: sdd has no controller-run task. Triage in a context file: not durable or reviewable. Re-triage to fill a vacated slot: open-ended within the deadline. Fixing prose with no seam: AC3 could not be shown. |
| D10 | The record's `## Verification` holds the review's own checks, run by Task 3 at the code head: coverage against Git, each fixed test red at `<fix>^` with the test overlaid and green at head, each filed or tracked issue open, any CR test a rejection cites. `just agent-workflow-tests` and `just build` run once in sdd's Final verification as AC4, `code (classified)`. AC1–AC3 are `evidence (classified)` rows that Task 3 measures into the plan's acceptance record, and the sdd controller writes every verdict. | writing-plans: no task runs the full declared verification. sdd final-review § Acceptance record (the implementer whose brief names a measurement writes its evidence) and § Final verification. Issue 425's plan, whose tasks wrote the acceptance record. The issue's criteria carry no kind tags. | Running the suite in Task 3 and copying it into the record: a second 16-minute run that the final gate repeats, and a fix-wave commit would make it stale. AC3 as `human`: the dispositions are checkable against the record and the tracker. |
