# Owners wait for the agents they start within the turn, issue 317

## Problem

In run-20261007-292-300 (#293 launch 2, #294 launch 2) a from-issue owner
launched its Phase-7 ship owner as a background agent, then ended its turn
with "Ship owner launched for PR #311; waiting for its completion
notification". No notification woke it. #294 launch 2 idled to its 3-hour
attempt deadline; the dispatcher then superseded it, which stopped the owner
and orphaned the ship owner mid-delivery.

Two texts invite this. The `own-commands` leaf-agent clause ends "never end
your turn while a command you started is still running", which owners read
as covering commands and not agents. And the canonical **Interim child
results** paragraph (from-issue, sdd; a slimmed copy in ship-issue) says an
owner "may end its own turn while the re-engaged child is live, because the
host wakes you with its next notification" (#261 D5). For a dispatched owner
that premise is false: a subagent that ends its turn has returned, and the
observed runs show nothing resumed it.

## Solution

One reworded clause and one reconciled paragraph, no new rule:

1. **The `own-commands` clause names agents** (per D1). Its constant and every
   enrolled carrier (nine skill carriers, four agent definitions) change its
   second sentence to:

   > If the host moves one to the background anyway, wait for it in the same
   > turn: never end your turn while a command or agent you started still runs.

   The first sentence is unchanged. The clause id stays `own-commands`. The
   reworded sentence is one byte shorter than the old one.
2. **Interim child results waits in the turn** (per D2). In the from-issue and
   sdd copies (which stay identical) and in ship-issue's copy, the
   end-your-turn allowance and its "host wakes you" premise are deleted; "and
   wait for that report" becomes "and wait for that report within your turn".
   In all three copies the undeliverable branch widens to "If the message cannot be delivered or
   its reply cannot be awaited in your turn, the child is one you cannot wait
   for", which routes to the existing **Writing workers** stop-and-release
   path instead of idling.
3. **No Phase-7-specific sentence** (per D3). The ship owner is a child agent;
   the owner's own prompt (orchestrate-issues' owner blockquote, or the prompt
   from-issue composes on `delegate`/`fresh_start`) carries the clause, and
   ship-handoff.md's fence carries it to the ship owner for the reviewers it
   starts. The `from-issue-ship-owner` dispatch marker and call line do not
   change.

A root session (interactive from-issue or ship-issue) is not a recipient of
the leaf-agent clauses, and the host does notify a root session; nothing
changes for it.

## Decisions

- **Clause text.** `own-commands`' second sentence is exactly the quoted text
  above in `CONTRACTS` and in each carrier's rendered region, exactly once,
  whitespace-normalized. `REMAINDER_PLACEHOLDER` ("four leaf-agent clauses")
  is unchanged because the count is unchanged.
- **Byte neutrality.** The Instruction Budget gate currently has zero headroom
  on every profile ceiling and one byte on the corpus. Every edited
  instruction document (skill file or agent definition) is no larger than at
  the base: the clause edit shrinks each copy by one
  byte before wrapping, and a carrier whose rewrap would add bytes is
  re-wrapped until it does not. The interim edits shrink from-issue, sdd and
  ship-issue. No ceiling is raised and no `instruction-budget-raise` label is
  needed (per D4).
- **Interim paragraph contract.** Ordered content of the from-issue/sdd copy:
  not a completion; re-engage by recorded identity; wait for that report
  within your turn; never a text-only reply, never suspend, never replace or
  stop; the worker stays registered; undeliverable or unawaitable → Writing
  workers route; only the final hand-back counts. No sentence permits ending
  the turn on a live child.
- **orchestrate-issues** changes only inside its owner-prompt blockquote (the
  carrier). Its notification case (a) for interim owner notifications is left
  to #310.

## Acceptance handling

AC1 `[code]` is met by the pinned contract test (test seams below). AC2
`[evidence]` is measurable only after merge: it needs one orchestrate-issues
run over two or more issues that reach Phase 7 on the merged skills. Per the
existing acceptance machinery, and the #292 AC5 precedent (per D5):

- the plan's acceptance map keeps it `evidence` (writing-plans never
  reclassifies) with the command "hand-back texts of the run's owner
  launches", condition "post-merge orchestrated run, ≥2 issues reaching
  Phase 7", threshold "zero matches of `waiting for`";
- the acceptance record row reads `not measured — post-merge` with Verdict
  `unverified`, which sdd's conformance axis carries as a surviving
  acceptance finding (the final-review fixer cannot re-measure it before
  merge, so it is an expected residual, not a defect), so `acceptance_state`
  is `unmet`;
- ship-issue therefore **holds** the issue open as `needs-verification` with
  its hold comment; the user closes it after observing a qualifying run.

## Test seams

Existing seams only:

- **Dispatch contracts** (`test_dispatch_contracts.py`). The updated
  `CONTRACTS["own-commands"]` constant re-pins every carrier through the
  existing source-tree, installed-tree, mutation, stray-copy and enrolment
  tests. One added test reads `guarded_documents()` and fails when any
  document still holds the commands-only tail ("never end your turn while a
  command you started") or the "host wakes you" premise, so a stale copy
  outside a region cannot survive (the `STALE_REMAINDER_WORDING` precedent).
- **Workflow skill contracts** (`InterimChildResultContractsTest`). The
  ordered anchors replace "You may end your own turn while the re-engaged
  child is live" with "and wait for that report within your turn." and the
  widened undeliverable anchor; identity of the from-issue and sdd copies
  stays pinned; ship-issue's paragraph is asserted to contain "within your
  turn" and no end-your-turn allowance.
- **Instruction Budget** (`just agent-instruction-budget`) passes unlabelled
  on the branch.

Verification: `just build` and `just agent-workflow-tests`, foreground with
explicit timeouts.

## Out of scope

- orchestrate-issues stall detection and its interim-owner case (a): #310.
- Runtime or helper code, hook enforcement of turn ends, and any host wait
  primitive; the clause stays outcome-worded with no tool named.
- Changing the Phase-7 dispatch call, its marker, or the dispatch-marker
  total.
- Codex configuration: the shared-tree text reaches Codex unchanged.
- Lowering instruction-load ceilings to the new measures (allowed, not
  required, unless a ceiling becomes more than 5% loose).

## Triage

Input: {"signals": {"contract_change": {"value": "hit", "evidence": "changes the leaf-agent dispatch clause contract that every carrier pins in test_dispatch_contracts.py"}, "concurrency_or_persistence": {"value": "no", "evidence": "prompt text and a source test only; no ledger, lock or persisted state changes"}, "open_design_questions": {"value": "doubt", "evidence": "the from-issue Interim child results rule currently permits ending the turn while a re-engaged child is live; reconciling it with the new clause is a design call"}, "criteria_shape": {"value": "hit", "evidence": "the second criterion is [evidence] from a later orchestrated run, which no deterministic code check verifies"}}, "paths": ["home/common/agent-skills/skills/from-issue/SKILL.md", "home/common/agent-skills/skills/from-issue/ship-handoff.md", "home/common/agent-skills/skills/sdd/SKILL.md", "home/common/claude-code/skills/orchestrate-issues/SKILL.md", "home/common/agent-skills/tests/test_dispatch_contracts.py"]}
Verdict: {"hits":["contract_change","open_design_questions","criteria_shape"],"lane":"full","mode":"shadow"}
ran: full (shadow)

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Reword `own-commands`' second sentence to "…wait for it in the same turn: never end your turn while a command or agent you started still runs.", keeping the id and the four-clause count | Issue: owners read the clause as commands-only; #261 D3 outcome wording with no tool named; exactly-once carrier rule; zero instruction headroom | A fifth `own-agents` clause: +~150 bytes in 13 carriers with no headroom, a count change in the placeholder and carrier tests, for the same rule |
| D2 | Interim child results: delete the end-your-turn allowance and its "host wakes you" premise in all three copies, wait "within your turn", and route an unawaitable reply to the Writing-workers stop-and-release path (partially reverses #261 D5) | Observed #293/#294 runs: the dispatched owner was never woken; Writing workers already says stop and release a worker you cannot wait for | Keep the allowance for re-engaged children only: the same false premise idles the launch; suspend `external`: #261 rejected it as the cascade |
| D3 | No Phase-7-specific sentence and no change to the ship-owner dispatch call; the clause in the owner's prompt is the one home | One home per rule (DRY); the agent-launch mode differs by host version, so naming foreground would be wrong on some hosts; marker total is pinned | State "launch in the foreground" at Phase 7: duplicates the clause, costs bytes with no headroom, and is unfollowable where agents always run in background |
| D4 | Every edited document ends no larger than at the base; no ceiling raise | Instruction Budget gate with zero headroom; agents may not apply the raise label | Raise ceilings under the label: only the user may apply it, and the change is expressible within budget |
| D5 | AC2 stays `evidence`, recorded `not measured — post-merge` / `unverified`; `acceptance_state` is `unmet` and ship holds the issue `needs-verification` for the user to close | writing-plans never reclassifies a tagged kind; conformance grades a missing measurement `unverified`; ship-issue Phase 0/8 hold; #292 AC5 precedent | Reclassify to `human` for `human_pending`: forbidden by writing-plans; grade it met from intent: self-attestation |
| D6 | Pin the change with the updated constant plus a stale-wording test over `guarded_documents()` and updated interim anchors; no new test file | Existing seams (#261 test seams); `STALE_REMAINDER_WORDING` precedent; the-bar Tests that can fail | A behavioural eval of owner turn-ends: no deterministic host seam exists; that is AC2's post-merge evidence |
| D7 | ship-issue's slim interim copy widens its undeliverable branch to "If the message cannot be delivered or its reply cannot be awaited in your turn, follow …" without the "the child is one you cannot wait for" gloss (refines the Solution's "in all three copies" wording for ship-issue only) | D4 byte neutrality: with the gloss ship-issue/SKILL.md grows by 12 bytes, without it it shrinks by 26; ship-issue's copy is already the slimmed variant and is not identity-pinned to the from-issue/sdd copy | Keep the gloss in ship-issue: the file grows past its base size against zero headroom, which D4 forbids |
