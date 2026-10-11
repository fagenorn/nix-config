# Issue 362 — say why the delegating owner relays a delegated return untouched

Issue: https://github.com/fagenorn/nix-config/issues/362. Follows https://github.com/fagenorn/nix-config/issues/352 (merged in pull request 358), whose spec and acceptance record are referred to below as "352's spec" and "352's record".

## Problem

When a from-issue owner delegates the rest of an issue to a fresh owner, that owner can come back in one of three ways that the delegating owner must pass on without doing anything else: a bare re-entry line, a `Suspended (…)` line, or a terminal workflow response. The skill text tells the delegating owner what to do (relay, write nothing, stop, no reap) but not why it is safe: that the delegated owner has already reaped, and that a terminal response means the delegated owner already ended the launch.

Eval 6 (`delegating-owner-handles-delegated-return`) expects an owner to give both reasons. It was graded fail three times under 352, the last time at 3c0090fb on exactly these two sub-clauses, so 352 merged with its third acceptance criterion `unmet`. An owner that does not know the reasons can also talk itself into a second reap or a second terminal write.

## Solution

State both reasons in the `delegate` action of `SKILL.md`, each next to the return it explains, and pay for the added bytes by deleting two clauses of the same file that restate their own sentence. Then grade evals 5, 6 and 7 once each on the final text and record the result in 352's record.

Eval 6 is not edited (D1).

## Decisions

### The two reasons, and where each attaches

The `delegate` action's first return case lists three returns and one instruction. The new text keeps that case and its instruction and adds one parenthesis to each group of returns:

Before:

> (a) only the re-entry line or a `Suspended (…)` line, or bytes valid at `--boundary workflow-response` as `terminal` or `terminal_failed`: relay it, write nothing and stop, with no reap;

After:

> (a) only the re-entry line or a `Suspended (…)` line (the delegated owner already reaped before its own exit), or bytes valid at `--boundary workflow-response` as `terminal` or `terminal_failed` (these alone mean it already ended the launch itself): relay it, write nothing and stop, with no reap;

Nothing else in the action changes: the order of the cases, the boundary names, the `progress` call and the bookkeeper exception stay byte for byte.

The reasons are attached separately, not as one clause for the whole case, because a design-time probe showed that an answerer repeats a reason only for the return it sits beside (see "Design-time probes").

### Each reason is true of every return it covers

Checked against the generic delegated owner's exits. `delegated-owner.md` § Generic delegate sends every exit except the handoff return through `SKILL.md`, "reap included".

| Return | Exit that produces it | Reaped before the exit? | Launch ended by the delegated owner? |
|---|---|---|---|
| Re-entry line | A rejected `progress` call: release workers, reap, print the line, write nothing | yes | n/a (not claimed) |
| Re-entry line | Terminal return procedure, `check-launch` answers `current: false`: the reap runs before the fence | yes | n/a |
| `Suspended (…)` line | Suspension procedure: release workers, reap, then `workflow-state suspend` | yes | n/a |
| `terminal_failed` bytes | Terminal return procedure: reap, fence, then its own `finish` | yes | yes, by its `finish` |
| `terminal` bytes | Suspension procedure whose `suspend` reply is a terminal replay, when the owner returns that reply alone: the reap ran before the call | yes | yes, by its exit; the attempt was closed by the anti-zombie bound |

Two wording choices follow from the table:

- "before its own exit", not "before its own exit write": two of the exits that print the re-entry line write nothing.
- "ended the launch" uses the word as Self-reap does ("every exit that ends this owner's launch"). In the `terminal` row the ledger closed the attempt, and the delegated owner's exit ended the launch. Either way nothing of the launch is left for the delegating owner to end, which is what the instruction relies on.

"These alone" carries the existing rule that any other valid workflow response (a `phase_gate` reply, for example) falls to the last case. It adds no rule.

### Paying for the bytes (D2)

The gate measures UTF-8 bytes of the documents each agent profile loads. `SKILL.md` is a hot member of three profiles. Headroom measured at the base (96174d0), in bytes: direct-autonomous controller 198, orchestrated issue owner 641, implementation owner 71. So the issue's "no headroom" is close but not exact: 71 bytes are free. The change still pays in full, as the issue asks.

| Edit to `SKILL.md` | Bytes |
|---|---:|
| Add ` (the delegated owner already reaped before its own exit)` | +57 |
| Add ` (these alone mean it already ended the launch itself)` | +54 |
| Delete `, whether the rejection meant a suspension or the `stopped(stalled)` bound` from the paragraph on a rejected `progress` call | −74 |
| Delete ` Suspension is NOT a terminal return.` from the end of the suspension procedure | −37 |
| Net | 0 |

Why the two deletions lose nothing:

- The rejected-`progress` paragraph already orders one unconditional sequence (do not retry, release, reap, print the line, stop, write no `finish`) for both rejection messages it names. The deleted tail only says the order does not depend on what the rejection meant.
- The sentence before the deleted one already says "make no `finish` call and emit no result JSON". The deleted sentence restates it in capitals.

Measured in a scratch worktree with these four edits applied: `SKILL.md` stays at 30409 bytes, `agent_tools.instruction_load check --base origin/main` prints `check: pass`, and the skill-text suites (`test_workflow_skill_contracts`, `test_dispatch_contracts`, `test_instruction_load`, `test_skill_lint`, `test_eval_cases`) run 284 tests, OK. No test pins either deleted clause.

`instruction-load.json` is not touched: no ceiling is raised, and none is lowered, since the measure does not move.

### No other file changes its instructions

- `delegated-owner.md`, `rollover.md`, `ship-handoff.md`, `AUTO.md`, `acquire-dispatcher.md`: unchanged. The delegating owner on the orchestrated route does not load `delegated-owner.md`, so the reasons cannot live there.
- `home/common/agent-skills/README.md` § Lifecycle helpers already gives the long form ("the delegated owner already ended or suspended the launch"); it needs no edit.
- `evals/evals.json`: unchanged (D1).

### Grading (D3)

The method is the one 352 recorded (352's spec D11, its plan's task 3 step 5), unchanged:

- One fresh `general-purpose` subagent per case, launched by type. Its whole prompt is the case's `prompt` verbatim, then the sentence "Answer from these files only, reading each in full first, and read nothing under any `evals` or `tests` directory:" and the absolute paths, in the worktree, of the five files `SKILL.md`, `AUTO.md`, `delegated-owner.md`, `ship-handoff.md` and `acquire-dispatcher.md` of the from-issue skill. It is not shown the expected output.
- The answer is compared with `expected_output` clause by clause. A case passes when every clause is stated or plainly implied by the answer and none is contradicted.
- Tighter for eval 6, from this issue's first criterion: the two sub-clauses that failed at 3c0090fb must be stated in the answer, not implied. They are "(a) and (b): the delegated owner already reaped before its own exit" and "(c): only `terminal` or `terminal_failed` bytes mean the delegated owner already ended the launch itself". An answer that says "before its own exit" where the case says "before its own exit write" states the clause: the fact graded is that the reap came first.
- Each of evals 5, 6 and 7 is graded exactly once, at one commit, after the skill edit is committed and with a clean tree. That commit's short id is recorded first.

What is never done (352's spec D13 stands): edit an expected output or a case prompt, grade the same text twice, or pick between two answers.

If a grading fails:

- The failure is recorded in full, naming each failed clause, and stays in the record.
- If a failed clause names a fact that none of the five files states, the skill text may be revised once more, paid for under the same budget rule, with a new ledger row saying what was added and why. All three cases are then graded once on the new commit.
- If every failed clause is stated in the five files (the answerer left it out), nothing is revised. The criterion is recorded `unmet`, 352's row keeps `unmet` with the new history, and the flow's ordinary handling of an unmet criterion applies. The same holds after the one permitted revision.

### "On the merged text"

The first two criteria are measured "on the merged text", and a branch cannot grade a commit that does not exist yet. The record therefore claims only this: the gradings were made at commit `<graded>`, and they stand for any commit whose five graded files are byte-identical to that commit's. The record's Conditions cell names the five files and the check `git diff --quiet <graded> HEAD -- <the five paths>`.

If a sync with `main` before merge changes any of the five files, the three cases are graded once more on the synced head and the record is extended, as 352 did after its fix wave and 354 after its sync. A sync that leaves the five files alone needs no regrade. Whether the merge commit satisfies the check is for whoever reads the record after merge; this change does not assert it.

### 352's record, AC3 row

Only the AC3 row of 352's record is edited, and only by extension:

- Observed: the existing history stays word for word; appended are the issue number 362, the three verdicts with their failed clauses if any, the contract-test and full-suite result lines, and the gate's output line.
- Commit: the graded commit is appended.
- Conditions: appended are the grader, the five files, the byte-identity check above, and that no case was edited.
- Verdict: `met` only when evals 5, 6 and 7 all pass, the four named contract tests and `just agent-workflow-tests` pass, and `just agent-instruction-budget` prints `check: pass`, all at the graded commit. Otherwise it stays `unmet`.

AC1, AC2 and AC4 of that record are not touched.

### Design-time probes

Two probes were run while writing this spec, each one fresh subagent answering eval 6's prompt from a scratch copy of the five files. They are not acceptance evidence and are not recorded in 352's record; the acceptance grading is the one made at the committed text.

- Probe 1, on an earlier wording (one clause for the whole case: "the delegated owner already ended the launch itself, reaping before any exit write, so relay it…"): the answer gave both reasons under (a), "same as (a)" under (b), and no reason under (c). That is the same shape as the 3c0090fb failure, which is why the reasons are now attached per return.
- Probe 2, on the wording above: the answer said under (a) that the delegated owner "already reaped and ended the launch itself", "same as (a)" under (b), and under the `terminal`/`terminal_failed` branch of (c) that "the child already ended the launch". It sent every other valid workflow response to the contract-failure case. No verdict is drawn from it here.

## Test seams

No new test. `docs/standards/agent-helpers.md` rule 6 lets a skill-text test pin only what a tool or subagent consumes; the two reasons are English prose for the reading agent.

1. **Existing contract tests** in `tests/test_workflow_skill_contracts.py`: `test_delegate_action_checks_the_return_before_it_ships` (the order of the dispatch id, the return line, the two boundary names, the `progress` call and the bookkeeper id inside the action), `test_delegated_return_line_is_spelled_identically_everywhere`, `test_generic_delegated_owner_returns_the_handoff_without_a_terminal_write`, `test_from_issue_evals_cover_the_delegated_ship_route`. The edit keeps every pinned string and their order.
2. **`just agent-workflow-tests`**, the whole suite.
3. **`just agent-instruction-budget`**, with no raise label.
4. **Evals 5, 6 and 7**, graded as above.

## Acceptance mapping

| # | Criterion | Kind | Verified by |
|---|---|---|---|
| 1 | Eval 6 passes, clauses (a) and (c) stated | code | Seam 4: one grading of eval 6 at the graded commit, with the tighter rule for the two sub-clauses. |
| 2 | Evals 5 and 7 still pass on the same text | code | Seam 4: one grading of each at the same commit. |
| 3 | Contract tests and budget gate stay green | code | Seams 1 to 3 at the graded commit. |
| 4 | 352's record shows AC3 as met | evidence | The AC3 row, extended as above; `met` only under its stated rule. |

## Out of scope

- Any change to what the delegating owner does with a return; this change adds reasons only.
- Helper, ledger or validator code, and any new test.
- A budget raise, and any edit to `instruction-load.json`.
- Eval 6's prompt and expected output, and every other eval.
- `rollover.md`'s relay stop for the direct-autonomous controller, which has the same shape and no eval asking for its reasons.
- Rows AC1, AC2 and AC4 of 352's record.
- Two gaps noticed while checking the exits and left alone: a delegated owner whose `suspend` reply is a terminal replay prints the re-entry line and relays the reply, so its return is two things at once and matches no single case; and the writing-workers rule lets an owner return "without a terminal write" without saying what it returns. Both land in the last case today, whose `check-launch` fence stops a second write.

## Triage

Input: `{"signals":{"contract_change":{"value":"no","evidence":"Instruction prose only: the delegate action's return handling is unchanged, one reason clause is added and paid for by cuts"},"concurrency_or_persistence":{"value":"no","evidence":"No helper, lock or ledger code changes; only skill markdown and an acceptance record"},"open_design_questions":{"value":"no","evidence":"The issue names the two missing facts and where they go; stating them in the text is the titled route"},"criteria_shape":{"value":"hit","evidence":"Four criteria, but the eval 5/6/7 gradings are read by a fresh grader, not a deterministic code check"}},"paths":["home/common/agent-skills/skills/from-issue/SKILL.md",".agents/artifacts/plans/2026-10-10-issue-352-delegated-ship-routing.acceptance.md"]}`

Verdict: `{"hits":["criteria_shape"],"lane":"full","mode":"shadow"}`

ran: full (shadow)

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | State both reasons in `SKILL.md`'s `delegate` action, one beside each group of returns it is true of; eval 6 is not edited (Q1). | The issue's titled route; both facts hold for every exit in the table above; 352's spec D13 allows no second case amendment without a new reason, and there is none. The orchestrated delegating owner loads `SKILL.md` and not `delegated-owner.md`. | Amending the case: the text, not the case, is what lacks the facts. One reason clause for the whole case: probe 1 showed the answer then gives no reason under the terminal-bytes return. Splitting the case in two: relabels the cases that 352's spec and the README cite, for no gain over the parentheses. |
| D2 | Pay the 111 added bytes in full by deleting two self-restating clauses of `SKILL.md` (74 and 37 bytes), net 0; leave `instruction-load.json` alone (Q2). | The issue: added text is paid for by cuts in the same change. `the-bar.md` token economy. Measured: gate passes, 284 skill-text tests pass, neither clause is pinned. | Spending the 71 free bytes: the sentence does not fit, and it leaves the tightest profile with nothing. Deleting Self-reap's last sentence ("After a `delegate`, the owner whose exit ends the launch reaps it"): it is the general rule the new parenthesis is an instance of, and it covers the delegating owner's own exits. Cutting from another file: only `SKILL.md` cuts offset `SKILL.md` growth in all three profiles. |
| D3 | Keep 352's grading method; grade each of evals 5, 6 and 7 once at one committed, clean head; require the two failed sub-clauses to be stated in eval 6's answer; on failure allow one text revision only for a fact the five files do not state, otherwise record unmet (Q3). | 352's spec D11 and D13; this issue's first criterion ("stated rather than implied"); `the-bar.md` truthful terminal states. | Regrading the same text, or revising until an answer passes: manufactures the evidence. Forbidding any revision: a genuinely missing fact found by the grading would then need a third issue. |
| D4 | The gradings stand for any commit whose five graded files are byte-identical to the graded commit's; a sync that changes one of them triggers one regrade of all three; the record claims nothing about the merge commit itself. | The criterion says "on the merged text", which no branch can measure; 352 and 354 both remeasured after the graded text changed. | Grading after merge: the criterion would stay open past the pull request that closes the issue. Claiming the merged text was graded: not true when written. |
| D5 | 352's AC3 row is extended, never rewritten, and its verdict becomes `met` by a stated rule the implementer applies. | The row's own history is the evidence of three failures; the rule is deterministic given the gradings. | Replacing the Observed cell with the new result: erases the failure history D13 says to keep. Leaving the verdict to a reviewer: this issue's fourth criterion is that the row shows `met`. |
| D6 | The design-time probes are disclosed in the spec and kept out of the acceptance record. | `the-bar.md` verify before claiming done, and D13's ban on choosing among gradings. | Not probing: the first wording would have reached the acceptance grading and failed on (c). Counting a probe as the grading: it ran on scratch text, not on a commit. |
| D7 | (plan) The grading task also writes the evidence columns of this issue's own acceptance record, in a second commit after the one that extends 352's row, so its AC4 row can cite that commit; the sdd controller writes its verdicts. | sdd's final review keeps one acceptance record per plan and has the measuring implementer write its evidence; 352's task 3 and 354's task 4 did the same. | Leaving the record to the final-review fixer: it would re-derive measurements it did not make. One commit for both records: a row cannot name the commit that contains it. |
| D8 | (plan) Grading has no inline fallback: an implementer that cannot launch a subagent reports blocked and the controller launches the three answerers. A launch that returns no answer is not a grading and is repeated once, noted in the record. The grader never repairs a failure: it reports, per failed clause, whether any of the five files states the fact; the one revision D3 allows is the controller's fix dispatch under D2's byte rule with its own ledger row, and the whole grading task then runs again on the new commit. Narrows 352's task 3, which allowed an inline grader. | This issue's first criterion asks for a fresh grader shown only the prompt and the skill files; the grading implementer has read the expected outputs. D3. | 352's inline fallback: the answerer would know the expected answer. Letting the grader revise the text: the measurer would be editing what it measures. |
| D9 | (plan) The grading task runs `just agent-workflow-tests` once at the graded commit, before any answerer is launched, and stops ungraded if it, the four contract tests or the budget gate fails. | D5 makes 352's verdict depend on the suite passing at the graded commit and puts its result line in the row; `writing-plans` otherwise keeps the declared verification for sdd's final gate. | Citing the final gate's run: it happens after the row is committed. Grading first: a failing check means the text changes and the gradings are spent for nothing. |
| D10 | (plan) The skill edit and the row extension are made by exact-match scripts carried in the task files: the edit writes nothing unless each old string occurs once and the byte count is unchanged; the row script appends to three cells, sets the verdict from six pass flags, and its check compares every other byte of the record with the graded commit. | D2's net 0 and D5's "extended, never rewritten" become checks that can fail; 354 edited skill text the same way. | Hand edits: one reworded clause moves the byte count, and a hand-edited 4 kB table row cannot be shown unchanged. |
