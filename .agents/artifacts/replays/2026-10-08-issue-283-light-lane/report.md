# #283 light-lane replay report

**Result: 11 of 11 issues triage `full`.** No issue triages `light`, including the
smallest, best-specified recent issues, so the defect-catch replay has no input.
The light lane as specified (design spec `2026-10-06-light-lane-budgets-design.md`,
rows D2–D4, D7, D14, D15) would never select the light route in this repository.

## Verdict against #283's criteria

| Criterion | Outcome |
|---|---|
| [evidence] #154 triages full | **met** — `full` (contract_change, open_design_questions, criteria_shape) |
| [evidence] every historical Important/Critical finding of each light-triaged issue scored; missed count reported | **vacuous** — zero light-triaged issues, so zero findings to score; missed = 0 by absence, not by measurement |
| [evidence] median light wall time vs the 90-minute budget, agent turns vs history | **not measurable** — no light run exists |
| [code] issues without retained findings reported unscored, never counted as passes | **met** — no issue is counted as a pass |

## Method

Delivered as a direct evidence job (decision recorded on #283). Blind triage: each issue
judged as a Phase-0 owner would, from the issue body and the code at its historical base
commit (first parent of the PR merge) only — no PR diff, findings, spec/plan artifacts or
later commits. Records evaluated with the shipped `lane-triage evaluate` from main against
the replay policy in `replay-light-lane-policy.json` (mode shadow; D16 areas mapped to
globs). The seven issues of the original replay set came first; #261, #270, #274 and #275
were added as the most light-shaped recent issues once the first seven all triaged full.
Per-issue records and verbatim verdicts are in `records/`.

Base commit = first parent of the issue PR's merge commit on main. Triage inputs: the issue body plus code at the base only.

| Issue | PR | Base commit | Verdict | Hits | Doubts | Rationale |
|---|---|---|---|---|---|---|
| #236 | #237 | 8836b641551b | full | contract_change, open_design_questions, criteria_shape, risk_path | none | Binding/invocation contract change; two alternative fixes left open; 5 criteria, one needs a live Codex run; predicted resolve_project.py if bindings are rejected up front |
| #238 | #239 | 5ad84230db9d | full | contract_change, concurrency_or_persistence, open_design_questions, criteria_shape | contract_change | Detector packaging undecided; activation migration deletes persisted home dirs; 6 criteria incl. PR-recorded measurement |
| #223 | #224 | 93bf5fd2cdff | full | contract_change, criteria_shape | criteria_shape | New `auto-owner` role in the closed, validated model-matrix role set; no written acceptance criteria (unclassifiable, D7) |
| #169 | #170 | 0c6f57e709e3 | full | contract_change, open_design_questions, risk_path | open_design_questions | workflow-response wire order + new budget-policy boundary; bound size unspecified; touches workflow-state.py |
| #190 | #196 | affa05e7392c | full | concurrency_or_persistence, risk_path | concurrency_or_persistence | Narrow bug fix with clear expected behavior and 2 deterministic criteria, but it sits in control's ledger transact (capacity over persisted custody) and in workflow-state.py |
| #221 | #225 | 3bb4d9db406b | full | contract_change, open_design_questions, criteria_shape, risk_path | none | New typed signal or non-final control action (left open); 5 criteria incl. skill text; workflow-state.py + _wire.py |
| #154 (neg. control) | #187 | 6c429066a288 | full | contract_change, open_design_questions, criteria_shape | open_design_questions | Checker contract + fixtures for all shared-skill examples; production checker boundary unidentified; 5 criteria incl. provenance recovery |

#154 triaged **full**, as the negative control requires.

Light-triaged issues: **none**. All seven triaged full, so the defect-catch replay (slice 5, step 2) has no issue to run.

Observations:
- `risk_path` alone would have forced full on #169, #190 and #221 (all workflow-state.py), so for those the judged signals are redundant.
- #190 is the nearest candidate for light. Its only judged hit is a `doubt` on persistence, and even if that doubt were cleared, its predicted path would still be a risk path.
- #223 would be light only if `criteria_shape` were judged `no` despite the issue having no written criteria, and if adding a role to the closed matrix were not judged a contract change.

## Extension: small recent issues

Same method, evaluator invocation, scratch `HOME` and policy root, and unchanged replay policy (`replay-light-lane-policy.json`). Base = first parent of the PR merge commit on main. #274 and #275 link a design spec under `.agents/artifacts/specs/` (present at base). Under the blindness rule those specs were **not** read, so each was judged from the issue body (which cites the spec's decision rows) and the base code only.

| Issue | PR | Base commit | Verdict | Hits | Doubts | Rationale |
|---|---|---|---|---|---|---|
| #261 | #267 | 6770ed9f207d | full | contract_change, concurrency_or_persistence | contract_change, concurrency_or_persistence | New settings.json Bash-timeout env plus a changed owner/child hand-back protocol (doubt); concerns live background jobs and orphaned children but no locking/ledger change (doubt); design fully stated; 4 test-checked criteria |
| #270 | #286 | 3b911376cfbb | full | contract_change, open_design_questions, criteria_shape | open_design_questions | Changes implementer tier in the closed validated matrix; one-tier-per-role matrix vs Sonnet-implementer/Opus-escalation split, and which fixer sites move, left unstated; re-evaluation-rule criterion is prose |
| #274 | #287 | 81210221ca45 | full | contract_change | none | Changes to-issues' criterion line format and adds a plan Acceptance map that plan review blocks on; otherwise all-no (4 [code] criteria, design decided) |
| #275 | #289 | 1365e979d13f | full | concurrency_or_persistence | none | Exists to stop two concurrent owners sharing a worktree; adapter-only, no contract change, design decided, 3 [code] criteria |

Light-triaged issues in the extension: **none**. That makes 11 of 11 full in total.

## Signal analysis

Over the 11 records (7 prior + 4 extension). A signal "fires" when it is `hit` or `doubt`; `risk_path` is derived from the predicted paths.

| Signal | Fired on | hit | doubt | Issues |
|---|---|---|---|---|
| contract_change | **9/11** | 7 | 2 | #154, #169, #221, #223, #236, #238 (d), #261 (d), #270, #274 |
| criteria_shape | 6/11 | 5 | 1 | #154, #221, #223 (d), #236, #238, #270 |
| open_design_questions | 6/11 | 3 | 3 | #154 (d), #169 (d), #221, #236, #238, #270 (d) |
| concurrency_or_persistence | 4/11 | 2 | 2 | #190 (d), #238, #261 (d), #275 |
| risk_path | 4/11 | 4 | n/a | #169, #190, #221, #236 |

Per verdict (all full):

| Issue | Signals firing | Carried by |
|---|---|---|
| #154 | contract_change, open_design_questions, criteria_shape | several (3) |
| #169 | contract_change, open_design_questions, risk_path | several (3) |
| #190 | concurrency_or_persistence, risk_path | several (2) |
| #221 | contract_change, open_design_questions, criteria_shape, risk_path | several (4) |
| #223 | contract_change, criteria_shape | several (2) |
| #236 | contract_change, open_design_questions, criteria_shape, risk_path | several (4) |
| #238 | contract_change, concurrency_or_persistence, open_design_questions, criteria_shape | several (4) |
| #261 | contract_change, concurrency_or_persistence (both doubt) | several (2), and the only verdict made entirely of doubts |
| #270 | contract_change, open_design_questions, criteria_shape | several (3) |
| #274 | contract_change | **single: contract_change** |
| #275 | concurrency_or_persistence | **single: concurrency_or_persistence** |

Findings:
- **`contract_change` fires on nearly everything (9/11).** In this repo almost every change touches a skill-to-skill, matrix or wire contract that tests pin, so the signal hardly discriminates. Yet it decides a verdict alone only once (#274). Drop it and 10 of 11 issues still triage full.
- The rule is a union, and 9 of 11 verdicts are over-determined (two or more signals). No single signal change would make the replay set light except on #274 (`contract_change`) and #275 (`concurrency_or_persistence`). On #261, light would need both doubts cleared.
- Every signal fires on at least 4 of 11 issues, so each is individually broad. The combined effect is that light is unreachable on this sample, even for the smallest, best-specified issues (#274, #275).

## Consequences

- **#282 (active light route) stopped before any commit; closed as not planned.** It would
  implement a route that triage never selects.
- **#284 (enable) closes as not enabled.** Its mechanical gate (0 missed, #154 full) is met
  only vacuously; switching to `active` with zero light verdicts adds no speed and no evidence.
- **Shadow triage (#279) stays.** Every new issue keeps recording a triage verdict, which is
  the data a recalibration needs.
- **The ceremony cost the light lane targeted is still real.** Since `contract_change` alone
  fires on 9 of 11 and dropping it leaves 10 of 11 full, an issue-level opt-out of the
  pipeline does not fit this repository; reducing ceremony inside the full pipeline is the
  lever left.
