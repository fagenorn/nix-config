# Light lane and lane budgets — design

Improvement B of the pipeline review. Sibling A (typed acceptance criteria and a
pre-merge acceptance audit) is designed separately; this spec consumes A's
criteria only through the interface named in D7 and does not design it. #270
(plan-driven implementers and fixers on Sonnet, reviews on Opus) is settled and
assumed.

## Problem

Every issue `from-issue` takes pays the full pipeline: design, grill, plan,
standards review, task-by-task `sdd`, ship. The 29-session dataset shows that
ceremony is mostly spent where it buys nothing. #261 changed 3 lines of code
behind about 740 lines of spec and plan. Per-task review caught about 3.5% of
defects; the rest surfaced at the final correctness review and at ship. Size
is no proxy for risk, either: #154 changed 0 code lines and drew 11 Important
findings. A cheaper lane is only safe if it is chosen by what makes a change
risky rather than by how big it is, if it keeps the review that actually
catches defects, and if it falls back to the full pipeline the moment it turns
out to be wrong.

The attempt budget is a flat 180 minutes for every issue
(`bindings.workflow.orchestration.attempt_budget_minutes`). That is too long
to tell a small change that has gone wrong from one that is just slow, and too
short for a large full-pipeline issue, which today runs into a deadline
suspension in the middle of a task.

## Solution

1. **Triage after investigation.** At the end of Phase 0, the owner writes a
   typed triage record, and `lane-triage` evaluates it under one closed rule
   (D2–D4). The result is `light` only when every signal is a clear "no".
   Any hit, and any doubt, gives `full`.
2. **Light lane.** The light lane replaces Phases 2–5 with a short design
   note. That note is committed at the spec path and doubles as a one-task
   plan (D5). One implementer builds the change. The unchanged `sdd` final
   review then runs both of its axes: the Opus correctness axis, and the
   conformance axis graded against the acceptance criteria (D6, D7). After
   that the change ships through the unchanged Phase 7.
3. **One-way escalation.** A light attempt becomes full on any Important or
   Critical finding before ship, on a second fix round, on the light deadline,
   or when the actual diff hits a risk signal triage did not predict (D8).
   Escalation resumes the full pipeline at Phase 2 in the same worktree. The
   design note is its seed, and the light commits are kept as a draft (D9).
4. **Lane budgets.** The ledger records each attempt's lane. Declaring
   `light` re-bases the deadline to the light budget, and escalating re-bases
   it to the full budget (D10, D11). At every task boundary, an owner that
   lacks headroom suspends cleanly with `blocked_on=deadline` (D12).
5. **Shadow before active.** The `light_lane` policy member starts in
   `shadow` mode: triage runs and is recorded, but every attempt runs full. A
   replay over #236, #238, #223, #169, #190 and #221, with #154 as a negative
   control, gates switching it to `active` (D13–D15).

## Decisions

**Project policy (`resolve-project`).** Add an optional member,
`bindings.workflow.light_lane`, closed to these keys:
`{ "mode": "shadow" | "active", "budget_minutes": <positive int>, "risk_paths": [<glob>, ...] }`.
When the member is absent or `null`, the light lane is unsupported. That is a
documented no-capability route: triage is skipped and every attempt runs full.
It is not a default. The `risk_paths` globs are relative to `project.root` and
come back exactly as authored, per the bootstrap rule for non-`paths` values.
`orchestration.attempt_budget_minutes` keeps its meaning as the full-lane and
acquisition budget, and enablement raises it to 240 (D11).

**Triage record and `lane-triage`.** A new `agent_tools.lane_triage` module
gets one command-table row, `lane-triage evaluate --repo-root <root> --input -`.
Its input is a closed record:
`signals.{contract_change, concurrency_or_persistence, open_design_questions, criteria_shape}`,
each `no | hit | doubt` with a one-line evidence string, plus
`paths: [repo-relative path, ...]`. Those are the paths that investigation
predicts, or, on re-check, the actual diff. The command reads `light_lane`
through `agent_tools.resolve_project`'s importable API and adds the derived
signal `risk_path` (any path matching any `risk_paths` glob). It prints
`{lane, mode, hits}`, where `lane` is `light` only if every signal is `no`.
`criteria_shape` is a hit when there are more than four acceptance criteria,
or when any criterion is not verified by a deterministic code check (D7). The
command writes nothing, and it exits 2 when the light lane is unsupported, so
the caller takes the full route.

**`workflow-state` ledger (schema 6 → 7).** Each attempt gains three fields:
`lane` (`null | light | full`), `lane_budget_minutes` (`null | int`), and
`lane_history`, a list of `{lane, reason, at}`. A new verb,
`declare-lane --repo-root --run-id --now --action-id --lane <light|full> --budget-minutes <n> --reason <r>`,
records the lane for the current launch of an active attempt. It re-bases
`deadline_at` to the current launch's `at` plus `n`. If that instant has
already passed, a `light` declaration is refused, and the owner declares
`full` instead. Transitions are monotonic: `null→light`, `null→full` and
`light→full`. Anything else is refused. `reason` belongs to the closed set
`triage`, `important_finding`, `second_fix_round`, `light_deadline`,
`unpredicted_risk`. A suspension resume re-bases using `lane_budget_minutes`
when it is set, and uses the request's `attempt_budget_minutes` otherwise. The
`control` and `direct-owner` request shapes and their interface versions are
unchanged.

**New `blocked_on` value `deadline`.** An owner can write it, and it is
auto-resumable. It means a clean suspension at a task boundary: workers
released, progress marker recorded. That differs from the reaper's `unknown`.
Anti-zombie accounting is unchanged.

**`from-issue` routes.** Phase 0 ends with triage. In `shadow` mode, the
owner records the result in the investigation note and in the ledger
(`declare-lane --lane full --reason triage`), and the would-be lane appears in
the note. In `active` mode, a `light` result declares light with the light
budget and takes the light route:

- The design note is written by the owner through `design` in note form. It
  has these sections: Triage, Problem, Solution, Acceptance criteria, Out of
  scope, Decision ledger, and a one-row Task index.
- Phase 6 runs `sdd` on that note as its plan: one implementer (Sonnet per
  #270), no separate per-task review, and the unchanged mandatory final
  review.
- Before Phase 7, the owner re-runs `lane-triage` on the actual diff paths.
- Phase 7 runs unchanged.

The task-level risk lanes (mechanical, low-risk, full) and the
`mechanical-only` shortcut keep their meaning. In this document, "lane" means
the issue-level lane (D1).

**Interactive mode.** At the Phase-0 checkpoint, the triage result is shown as
the recommended lane. The user may force `full`. Forcing `light` against a hit
is not offered.

## Test seams

All of these are existing seams under `just agent-workflow-tests`. Nothing new
is invented.

- **`resolve-project` schema tests** (`test_resolve_project.py`): the
  `light_lane` member's closed shape, mode and glob validation, and that
  absent or `null` means unsupported.
- **`workflow-state` command tests** (`test_workflow_state.py`, following the
  `mark-progress`/`register-worker` prior art): `declare-lane` transitions,
  refusals and deadline re-basing, the schema-7 migration, the lane-aware
  resume re-base, and `suspend --blocked-on deadline`.
- **`lane-triage` package tests** under `tests/`, driving
  `python -m agent_tools.lane_triage` against a fixture project, per the
  agent-helpers standard rule 5. The launcher row is covered by
  `test_agent_tools_launchers.py`.
- **Skill contract tests** (`test_workflow_skill_contracts.py`): the
  `from-issue` text names the triage step, the escalation triggers and the
  boundary-suspension rule; `sdd` names the `deadline` suspension.
- **Replay** (slice 5) is evidence, not a test. Its report is the enablement
  gate.

## Out of scope

- Sibling A's criteria taxonomy and its acceptance audit. This spec consumes
  them only through D7.
- Model routing (#270).
- Changing per-task risk lanes, the final review's rubrics, or `ship-issue`'s
  review.
- Lane-aware admission or slot accounting in `control`.
- A third lane, or any automatic lane change other than escalation to full.
- De-escalation from full to light.
- Learning `risk_paths` from history. They are authored by hand.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Name it the issue-level **lane** (`light`/`full`), distinct from the existing per-task risk lanes; `mechanical-only` stays as-is | from-issue §Risk lanes already owns "risk lane" per task | Fold into task lanes: they narrow per-task review, which finds ~3.5% of defects; that is the wrong lever |
| D2 | Triage signals: contract/schema change, concurrency or persistence, open design questions, criteria shape, and the policy risk-path map. No size signal | #154 (0 lines, 11 Important); caller proposal | Line-count threshold: the dataset shows size does not predict risk |
| D3 | `lane = light` only if every signal is `no`; `doubt` counts as a hit | Caller proposal ("any doubt ⇒ full"); Truthful terminal states | Weighted score: unfalsifiable, and its tuning has no evidence base |
| D4 | The rule lives in a pure `lane-triage` package command; the judgment per signal stays with the Opus owner | agent-helpers standard rules 1–2; replay needs a deterministic evaluator | Rule in skill prose only: the replay could not measure it. Rule inside `workflow-state`: that would make the ledger load policy |
| D5 | The light design note is written at the spec path (`…-design.md`) with a one-row Task index, so `sdd`/`review-package` consume it unchanged and escalation extends the same file | The decision ledger is the issue's single decision store (from-issue) | Separate note file: two ledgers on escalation. A dedicated light plan format: new consumer code for no gain |
| D6 | The light lane keeps the full `sdd` final review (Opus correctness, plus conformance) and Phase 7 unchanged; it drops Phases 2–5 and the per-task review | Dataset: defects surface at final review and ship; sdd final-review is "mandatory for every lane" | Also drop the final review, or swap it for reviewer-lite: that removes the gate that actually catches defects |
| D7 | A `criteria_shape` hit is more than 4 criteria, or any criterion not checked by a deterministic code check (in A's terms: any non-code criterion). Without A, the criteria as written in the issue count, and an unclassifiable one is `doubt` | Caller proposal (measurement criteria ⇒ full); keeps A abstract | Only measurement criteria count: A's human or evidence criteria also need gates the light lane drops |
| D8 | Escalate on: any Important or Critical finding before ship; a second fix round; the light deadline; or an unpredicted risk hit on the actual diff | Caller proposal, plus a re-check because predicted paths can be wrong | Any finding at all: Minor findings are routine. Escalating at ship: see D9 |
| D9 | Escalation resumes at Phase 2 in the same worktree; the note seeds the design; light commits are a draft the plan may keep or rewrite; findings become ledger rows. Ship-time findings use ship's own loop and are recorded as a lane miss, with no re-plan | Resume-in-place model (#133); "back up a phase" rule in from-issue | Discard the branch: throws away valid work. Re-plan at ship: Phase 7 has no route back to Phase 2 |
| D10 | Acquisition always uses the full budget; `declare-lane` re-bases from the launch start; the lane and its budget persist on the attempt and drive suspension-resume re-bases (schema 7) | `control`/`direct-owner` take `attempt_budget_minutes` per request; `resume_attempt` re-bases | Pass a lane at acquisition: triage happens after acquisition. Bump both request interfaces: wider blast radius |
| D11 | Budgets: light **90**, full **240** minutes | Caller proposal; today a flat 180 and #261–#265 owners hit mid-task deadlines; slice 5 measures light wall time against 90 | Keep 180 for full: large issues already hit mid-task deadlines |
| D12 | At each task boundary, an owner whose remaining time is below max(15 min, its longest completed task this launch) releases workers, marks progress and suspends with new auto-resumable `blocked_on=deadline` | Suspension procedure; mark-progress (#250); the reaper's expiry lands mid-task | Rely on the reaper: dirty mid-task suspensions with live workers. Reuse `unknown`: hides clean versus dead owners from budget tuning |
| D13 | `light_lane` is optional policy with a closed `mode: shadow\|active`; absent or `null` is the unsupported route | Bootstrap "no project policy is defaulted"; the `release: null` precedent | An always-on lane: unvalidated. An env flag: policy belongs in project.json |
| D14 | The replay set is #236, #238, #223, #169, #190 and #221, plus **#154 as a negative control** that must triage `full` | Caller list; #154 is the dataset's size-versus-risk counterexample | Caller list alone: none of the six tests that a "small" contract change is caught |
| D15 | Enablement (`shadow` → `active`, budgets 240/90) is an autonomous slice gated mechanically on the committed replay report: 0 `missed`, #154 `full`, every scored issue reported; otherwise the slice records the failure and leaves `shadow` | User directed fully autonomous, evidence-based delivery (2026-10-06); `mode` is a one-line revert | A human enablement step: the evidence gate is the decision, a human would only re-read it |
| D16 | Risk-path globs for this repo are seeded from contract-bearing areas: lifecycle guard, `workflow-state`, transaction core, `resolve-project` schema, delivery contract, `.agents/project.json` | CLAUDE.md names these as guarded or contract surfaces | No seed: the map would be empty, and every signal would rest on judgment |

## Proposed slices

1. **Shadow triage, end to end** (autonomous; blocked by none). Adds the
   `light_lane` policy member, `lane-triage`, and the Phase-0 triage record.
   The lane is always run as full.
   - Resolver schema tests: `test_resolve_project.py` accepts a valid
     `light_lane`, rejects unknown keys, a bad `mode` and a non-positive
     budget, and treats absent and `null` as unsupported.
   - Package tests under `tests/`: `lane-triage evaluate` returns `light` only
     for an all-`no` record; any `hit` or `doubt` gives `full`; a path
     matching a `risk_paths` glob adds `risk_path` to `hits`.
   - The same package tests: `lane-triage` exits 2 when `light_lane` is
     absent.
   - `test_workflow_skill_contracts.py`: `from-issue` Phase 0 names the
     triage record and the shadow behavior.
2. **Lane ledger and budgets** (autonomous; blocked by none). Covers schema 7,
   `declare-lane` and the lane-aware resume.
   - `test_workflow_state.py`: `declare-lane --lane light --budget-minutes 90`
     sets `deadline_at` to the launch `at` plus 90 minutes and appends a
     `lane_history` entry.
   - The same suite refuses `full→light`, `light→light`, a non-current launch,
     and a light declaration whose re-based deadline has already passed.
   - The same suite: a suspended light attempt resumes with a 90-minute
     window, and an attempt with no lane resumes with the request budget.
   - The same suite: a schema-6 ledger migrates with the three new attempt
     fields set to `null`, `null` and `[]`.
3. **Clean deadline suspension** (autonomous; blocked by 2). Covers
   `blocked_on=deadline` and the boundary rule in `sdd` and `from-issue`.
   - `test_workflow_state.py`: `suspend --blocked-on deadline` is accepted and
     auto-resumable, and is refused while a registered worker is live.
   - `test_workflow_skill_contracts.py`: `sdd` states the D12 headroom rule
     and the order release → `mark-progress` → suspend.
   - `test_workflow_state.py`: `control` resumes a `deadline` suspension
     without a human-directed request.
4. **Active light route and escalation** (autonomous; blocked by 1, 2). Covers
   the note form, the one-implementer `sdd` run, the actual-diff re-check and
   the D8 triggers.
   - `test_workflow_skill_contracts.py`: `from-issue` names the light route's
     note sections, the reuse of the one-row Task index, the unchanged final
     review, and each D8 trigger, each mapped to its `declare-lane` reason.
   - The same suite: `design` documents note form, and escalation resumes at
     Phase 2 with the same spec path.
   - `lane-triage` package tests: the actual-diff re-check returns
     `risk_path` for a diff path that was absent from the predicted set.
5. **Replay validation** (autonomous; blocked by 1, 4; gates 6).
   - Triage replay: for each D14 issue, a Phase-0 triage is run from the issue
     body at its historical base commit, and the triage record and the
     `lane-triage` output are committed to the replay report. Measured in the
     report: #154 is `full`.
   - Defect-catch: each issue that triaged `light` runs the light lane in a
     scratch worktree, from its historical base, up to the end of Phase 6,
     with no forge writes. Its final-review findings are compared with that
     issue's historical Important and Critical findings. Measured in the
     report: each historical finding is `caught`, `escalated`, `absent` (a
     reviewer confirms the defect is not in the light diff) or `missed`, and
     the number of `missed` findings is 0.
   - Cost: the report gives wall time and agent turns for the light replays
     against the historical sessions. Measured in the report: the median
     light wall time is at or under 90 minutes.
   - An issue with no retained findings is reported `unscored` and never
     counted as a pass.
6. **Enable** (autonomous; blocked by 5; ships only when the report shows 0 `missed` and #154 `full`, else closes as not-enabled with the report linked). Authors `light_lane`
   `{mode: active, budget_minutes: 90, risk_paths: D16}` and sets
   `attempt_budget_minutes: 240` in `.agents/project.json`.
   - `resolve-project resolve` on main returns that `light_lane` member.
   - `just agent-workflow-tests` and `just build` pass on the enabling PR.
   - The PR links the slice-5 report showing 0 `missed` findings.
