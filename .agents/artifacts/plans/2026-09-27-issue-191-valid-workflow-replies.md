# Valid Workflow Replies Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** every `workflow-state` reply a lifecycle skill decodes passes its own
`artifact-budget validate-report --boundary workflow-response` check
([#191](https://github.com/fagenorn/nix-config/issues/191)). That covers
reconciled merges in control summaries and direct terminal replays, `progress`,
and `suspend`.

**Architecture:** Task 1 adds artifact-budget's ledger-result rule and composes
it into the two workflow-response result slots only. Owner reports stay on the
owner rule. Task 1 also gives the lifecycle test harness one boundary-validating
helper. Task 2 makes `progress` reply with a closed v2 `phase_gate`: the
delivery model's validator branch, the producer in `workflow-state`, and a
harness `progress()` that validates every reply. Task 3 does the same for
`suspend`: `suspended`, or the existing `terminal` replay at the stall bound.
Task 4 makes from-issue name what it reads, pins that wording, raises the
breached instruction-load ceilings and runs the final gate.

**Tech stack:** Python 3 standard library (`unittest`, `subprocess`, `json`,
`ast`), Markdown skill prose, the instruction-load JSON model, `just`.

Spec (the source of truth; read it whole):
`.agents/artifacts/specs/2026-09-27-issue-191-valid-workflow-replies-design.md`,
decision ledger D1–D11.

## Global Constraints

- Scope is exactly the spec's (D1), and its `## Out of scope` list binds. That
  means:
  - no change to `reconciled_result` or `reconcile_merged_attempt` beyond one
    docstring sentence, no schema bump and no load-time repair (D2, D4);
  - no `result_source` on the wire (D3), no new `--boundary` value, and no
    change to owner-report strictness at either ship-summary boundary or to
    `finish`'s inner check;
  - no launch fencing of `progress` or `suspend`;
  - `AUTO.md` and every document other than `from-issue/SKILL.md` unchanged
    (D8).
- The helpers are legacy flat scripts under `home/common/agent-skills/scripts/`
  and stay there (`docs/standards/agent-helpers.md`: a cluster moves in its own
  PR). New code adds no `sys.path` edits, no `importlib` loads and no
  `__file__` lookups.
- Both new reply kinds carry `interface_version: 2`. `_workflow_response`
  stays a closed dispatch whose fallthrough is `_reject()`.
- `DeliveryRuntime.custody_for_record`, reached as `_delivery().custody_for_record`,
  renders every `custody` in these replies. `workflow-state` composes no action
  id for them.
- Run targeted tests from the worktree root as
  `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/<file>.py -k <pattern>`,
  and summarize output with
  `2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'`. A full
  `test_workflow_state.py` run takes about 12 minutes, so use `-k` in inner
  loops and run the whole file once per task gate.
- `just build` runs once, in Task 4's final gate. Never run `just switch`.
- Commits are conventional and SSH-signed. Never disable signing, and surface a
  signing failure. Each message ends with the line
  `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Path abbreviations in members: `S` = `home/common/agent-skills/scripts`,
  `T` = `home/common/agent-skills/tests`, `SK` = `home/common/agent-skills/skills`.

## Test seams

These are the spec's five seams, and there are no others (D7, D9):

1. **Real lifecycle CLI → real boundary CLI** in `T/test_workflow_state.py`.
   `LifecycleHarness.validated_response` (Task 1) backs `control_validated`,
   `progress()` (Task 2), `suspend()` (Task 3) and the raw direct replays.
   Ledger assertions read the ledger.
2. **artifact-budget CLI** in `T/test_artifact_budget.py` (Task 1).
3. **Delivery-model validator** in `T/test_delivery_model.py`, over
   `_delivery_model_fixtures.workflow_responses` (Tasks 2 and 3).
4. **Skill contracts** in `T/test_workflow_skill_contracts.py` (Task 4).
5. **Instruction load**: `T/test_instruction_load.py`'s live-tree ceiling test
   (Task 4).

No test calls a private helper to prove a reply shape.

## Delivery estimate and boundaries

These figures are estimates. They come from a planning probe that applied every
member's code and tests, as written, to a scratch copy of `e5953a6`. The probe
did not apply Task 1's docstring edit or run `just build`.

- Ten files change and none is created: three helpers, five test files,
  `SKILL.md` and `instruction-load.json`. The diff is about +524/−73 lines, and
  about 317 of those lines are in `test_workflow_state.py`.
- The largest risk is test churn. Validating every `progress()` reply turns 13
  existing tests red until their field reads move to `action` or to the ledger.
  Task 2 lists every edit. Task 3 rewrites four `suspend()` call sites in three
  tests.
- Every watch-it-fail step failed as its member says. Every targeted gate
  passed. Eleven tests are added: 1 in `test_artifact_budget`, 6 in
  `test_workflow_state`, 2 in `test_delivery_model` and 2 in
  `test_workflow_skill_contracts`, net of none removed. With all four members
  applied, the probe's `just agent-workflow-tests` gave `Ran 1373 tests` and
  `OK (skipped=3)` in about 24 minutes. The base count is derived as 1362.
- Tasks run in index order. Tasks 2 and 3 consume Task 1's helper, and Task 3
  also consumes Task 2's fixture-set edit. Tasks 1–3 are each independently
  shippable. Task 4's prose only states behavior that exists once Tasks 2 and 3
  have landed.

## Task index

Task 1 — Ledger-result rule for workflow-response result slots — `S/artifact_budget.py`, `S/workflow-state.py`, `T/test_artifact_budget.py`, `T/test_workflow_state.py` — full — [task-1.md](2026-09-27-issue-191-valid-workflow-replies.tasks/task-1.md)

Task 2 — `progress` replies with a closed v2 `phase_gate` — `S/delivery_model/_wire.py`, `S/workflow-state.py`, `T/_delivery_model_fixtures.py`, `T/test_delivery_model.py`, `T/test_workflow_state.py` — full — [task-2.md](2026-09-27-issue-191-valid-workflow-replies.tasks/task-2.md)

Task 3 — `suspend` replies with a closed v2 `suspended` or the stall-bound `terminal` replay — `S/delivery_model/_wire.py`, `S/workflow-state.py`, `T/_delivery_model_fixtures.py`, `T/test_delivery_model.py`, `T/test_workflow_state.py` — full — [task-3.md](2026-09-27-issue-191-valid-workflow-replies.tasks/task-3.md)

Task 4 — from-issue names the replies it reads, ceilings, final gate — `SK/from-issue/SKILL.md`, `T/test_workflow_skill_contracts.py`, `home/common/agent-skills/instruction-load.json` — full — [task-4.md](2026-09-27-issue-191-valid-workflow-replies.tasks/task-4.md)

All four tasks are `full`. Each one changes a public wire contract (the
workflow-response boundary and two lifecycle replies) or the lifecycle skill
contract that consumes it.

## Criterion → task trace

| Spec requirement | Task |
|---|---|
| Solution 1: the ledger-result rule on terminal and control-summary result slots; owner reports stay strict (D2–D4, D10) | 1 |
| Acceptance 1: a contractless reconcile validates on this and later sweeps, tracker `closed` and `open` | 1 |
| Acceptance 2: the persisted #154 shape and raw direct replays (bare, `present`, `unpublished`) validate | 1 |
| Solution 2: `progress` → closed `phase_gate`; no stale handoff echoed (D5) | 2 |
| Solution 3: `suspend` → closed `suspended`, or the `terminal` replay at the stall bound (D6) | 3 |
| Seam 1: every real `progress`/`suspend` reply is piped through the boundary (D7, D9) | 1 (helper), 2, 3 |
| Solution 4: from-issue names `phase_gate`'s `action`, pipes suspend's reply, and handles a stall-bound `terminal`; ceilings are raised with notes (D8) | 4 |
| `just agent-workflow-tests` and `just build` pass | 4 (final) |

## Decisions

The spec's `## Decision ledger` is authoritative. The members cite D1–D8 from
the design. Planning added two rows. **D9** fixes the test-seam mechanics: one
`validated_response` helper, `suspend()` returning the decoded reply, and the
contractless-ledger recipe. **D10** fixes the ledger-result rule's dispatch on
the reconciliation signature and the keyword-only `rule` argument. The ceiling
raise follows #155 D10 and D29 unchanged.

## Standards review provenance

- Reviewer: **Claude fallback** (native `reviewer`, Opus/high, fresh context,
  read-only), reviewing HEAD `9c76a78` on base `6ab576e`. Codex (`codex-review`,
  `gpt-6-astra`/`xhigh`, read-only sandbox, ephemeral) ran first and completed,
  but its JSONL carried no runtime-selection event, so the model and effort could
  not be verified. That is a metadata failure, which takes the one native
  fallback with the same packet. Codex's single finding (an unpiped `just build`
  gate) was then verified independently against the live plan and accepted.
- Accepted 5: commit trailers in every member's commit step; the
  `validate_ledger_result` docstring now matches D3; a note on the seam-2
  placement (task 1); a corrected suite rationale (task 2); the unpiped build
  gate (task 4).
- Rejected 2: a parity test per closed-set value (per D11); rescoping SKILL.md's
  "Suspension is NOT a terminal return." (low confidence, since the sentence
  governs only the suspension path, and task 4 pins it byte for byte).
- Deferred 0.
