# Review-Code Routing Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** ship-issue's and sdd's correctness axis route on the retained
`capabilities.review.code` state before anything is dispatched, so an
`unsupported` project never reaches Codex, and a Codex capacity rejection stops
only on the `available` route
([#195](https://github.com/fagenorn/nix-config/issues/195)).

**Architecture:** This is a change to skill prose, plus contract tests. Task 1
changes the places that own the rules. The configured-review paragraph that
ship-issue and sdd share gets the `available`-route capacity scope and the
routing-error classification. `codex-collaboration` gets the same scope, and
under `unsupported` it makes no Codex call. Task 2 turns ship-issue Phase 5's
correctness sentence into the three-rung ladder and the routing-error action,
and adds the ladder test helper. Task 3 makes the same change in sdd's final
review and the two sdd sentences that restate it, then runs the final gate.

**Tech stack:** Markdown skill prose, Python 3 `unittest` (stdlib), `just`.

Spec (source of truth, read it whole):
`.agents/artifacts/specs/2026-09-27-issue-195-review-code-routing-design.md`,
decision ledger D1–D11.

## Global Constraints

- Scope is exactly the spec's. Its `## Out of scope` list binds: no Python
  helper, resolver, workflow-state, `diff-scope` or review-package change, no
  plan-review routing change, no change to the degradation gate's
  `capabilities.review.code` clause, and no eval change (D3, D11).
- Every `<!-- agent-dispatch: … -->` marker and the `Agent(…)` call line under it
  stay byte for byte as they are, and so do their ids, roles, models and efforts.
  `home/common/agent-skills/model-matrix.json` does not change (D8).
- Vocabulary: "available" names only the capability state. The skill's presence
  is "installed" (D5). No edited route text keeps the word "unavailable".
- ship-issue `REVIEW.md` and sdd `final-review.md` carry one configured-review
  paragraph, and the two copies stay byte-identical (D7, D10).
- Each rule has one home per document family. The capacity terms and the
  routing-error classification live in the configured-review paragraph and in
  `codex-collaboration`'s capacity paragraph. The callers' dispatch sites carry
  the ladder and the routing-error action (D9).
- Prose is inserted exactly as the members give it. Every quoted sentence is
  pinned by a test in the same task.
- No new file is created. `final-review.md` gains no code fence, because the
  dispatch-contract suite would then enrol it as a template carrier.
- Run targeted tests from the worktree root as
  `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/<file>.py -k <pattern>`.
  Summarize the output to the `FAIL:`/`ERROR:` ids and the `Ran`/`OK`/`FAILED`
  lines.
- Shell gates normalize whitespace with `LC_ALL=C tr -s '[:space:]' ' '`. Under
  the UTF-8 locale, this machine's GNU `tr` splits multibyte characters such as
  `—` and `→`, and a prohibition can then pass for the wrong reason.
- `just build` runs once, in Task 3's final gate. Never run `just switch`.
- Commits are conventional and SSH-signed. Never disable signing, and surface a
  signing failure. Each message ends with the two trailer lines
  `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_014t9cPhYQiiTKbbAn8vTEaq`.

Path abbreviations used in members: `T` =
`home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `SK` =
`home/common/agent-skills/skills`, `CC` =
`home/common/claude-code/skills/codex-collaboration`.

## Test seams

- **Skill-contract text seam** (per D3): `T`, class `ProjectPolicySurfaceTest`.
  Its tests read whitespace-normalized skill text and use `assert_ordered`.
  - The two pair helpers, `assert_configured_code_review_pair` and
    `assert_codex_operation_pair`, gain the shared `CAPACITY_SCOPE_ANCHORS`
    (Task 1). This covers AC2 and the paragraph half of AC3.
  - `test_review_capability_routes_before_command_lookup` gains the
    `codex-collaboration` "makes no Codex call" anchor and the DIFF-REVIEW
    clause (Task 1). This covers AC1's `codex-collaboration` half.
  - The new `assert_correctness_route_ladder` helper, with its self-checks,
    covers AC1, AC4 and the caller half of AC3 (Tasks 2 and 3, per D10).
- **Unchanged guards** for AC5: `test_dispatch_contracts.py`,
  `test_agent_model_matrix.py` and `test_shell_example_contracts.py` must stay
  green with no edit.

## Delivery estimate and boundaries

These figures are estimates. They come from a planning probe that applied every
member, as written, to a scratch copy of `87ad07e`. Eight files change and none
is created. In seven skill documents, about 39 lines are added and 22 removed.
In `T`, about 182 lines are added and 3 removed. The diff fits one review
package. Tasks run in index order. Task 3 uses Task 2's helper, and Task 3's
final gate covers all three. The plan adds 5 tests: 1 in Task 1, 2 in Task 2 and
2 in Task 3. The four contract suites named in each member's gate go from 217 to
222 tests. `just agent-workflow-tests` goes from 1316 to 1321, with 3 skips
before and after.

## Task index

Task 1 — Scope the capacity rule to the `available` route, and make `codex-collaboration` make no Codex call under `unsupported` — `SK/ship-issue/REVIEW.md`, `SK/sdd/final-review.md`, `CC/SKILL.md`, `CC/DIFF-REVIEW.md`, `T` — full — [task-1.md](2026-09-27-issue-195-review-code-routing.tasks/task-1.md)

Task 2 — ship-issue Phase 5 routes the correctness axis on `capabilities.review.code` — `SK/ship-issue/SKILL.md`, `SK/ship-issue/REVIEW.md`, `T` — full — [task-2.md](2026-09-27-issue-195-review-code-routing.tasks/task-2.md)

Task 3 — sdd's final review routes the correctness axis the same way, then the final gate runs — `SK/sdd/final-review.md`, `SK/sdd/SKILL.md`, `SK/sdd/correctness-reviewer-prompt.md`, `T` — full — [task-3.md](2026-09-27-issue-195-review-code-routing.tasks/task-3.md)

All three tasks are `full`. Each one changes the routing, stop or fallback
behaviour of a skill-to-skill review contract, a public contract that also
decides whether the lifecycle stops or suspends.

## Criterion → task trace

| Criterion | Task |
|---|---|
| AC1: ship's `unsupported` rung reaches `ship-issue-full-correctness-fallback` and names neither `diff-review` nor `bindings.commands` | 2 |
| AC1: `codex-collaboration` "makes no Codex call" before its command dereference | 1 |
| AC2: `available` rung names `diff-review`, then the capacity rejection | 2 (ship), 3 (sdd) |
| AC2: shared paragraph and `codex-collaboration` scope the capacity rule to the `available` route | 1 |
| AC3: "routing error, never a capacity rejection" in both paragraphs | 1 |
| AC3: routing-error action at both dispatch sites | 2 (ship), 3 (sdd) |
| AC4: the sdd ladder, with `correctness-reviewer-prompt.md` as its rung-3 target | 3 |
| AC5: markers unchanged, pinned phrases hold, `just agent-workflow-tests` and `just build` pass | every task's gate; 3 (final) |

## Decisions

The spec's `## Decision ledger` is authoritative, and the tasks cite D1–D9 from
the design. Planning added two rows. **D10** pins every reworded routing
sentence and the byte identity of the shared paragraph, and fixes the ladder
helper's anchors and self-checks. **D11** leaves the eval corpus untouched and
records why the existing evals still grade correctly. Standards review added
**D12** (the helper pins rung 3's no-invocation clause, with one mutant per
caller) and **D13** (REVIEW.md's template line says "native correctness form").

The probe applied every member to a scratch copy of `87ad07e`. Each
watch-it-fail step failed as its member says, and each targeted gate passed.
Every ship mutant in Task 2's self-check was confirmed to raise on the clause it
names. The four contract suites ran 222 tests, all `OK (skipped=3)`. The probe
ran `just agent-workflow-tests` twice. At base it gave `Ran 1316 tests` and
`OK (skipped=3)`. With all three tasks applied it gave `Ran 1321 tests` and
`OK (skipped=3)`. The probe did not run `just build`. The standards-review
edits (D12, D13) came after the probe. They add one assertion to the helper, one
`assertIn` and one mutant subtest in Task 2, one mutant in Task 3, and a one-word
REVIEW.md edit. Their expected counts are derived, not probed, and test totals
do not change.

## Standards review provenance

- Reviewer: Claude fallback (one fresh native `reviewer`, Opus, read-only,
  against `REVIEW-CONTRACT.md`). Codex `plan-review` ran first and completed,
  but its JSONL carried no runtime-selection event naming the selected model
  and reasoning effort, so Codex identity was not established. That is a
  metadata failure, so the one-time native fallback ran with the same packet.
  Codex was not retried. Its completed finding was verified against the live
  worktree like any other finding.
- Base `17da7f2`, plan reviewed at `312f01c`; no focus configured.
- Findings: 0 Blocking. Should fix: 2 accepted. The rung-3 no-invocation
  clause was unpinned (Tasks 2 and 3, D12). REVIEW.md's stale "native
  correctness fallback" was changed (Task 2, D13); its `SKILL.md` "fallback
  rubrics" half was rejected, because that phrase names the template-fallback
  rubrics. Discussion: 2. The conformance launch precedes the ladder in reading
  order: declined, because ship's phase-entry preamble already stops `blocked`
  and the markers stay where they are (D8). The sdd self-check was weaker than
  ship's: covered by D12's sdd mutant. Accepted 3, rejected 1 (the half-finding),
  deferred 0.

---
