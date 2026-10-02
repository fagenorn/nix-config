# Companion-Only Review Binding Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** `codex-collaboration` and its two callers support exactly one review binding shape, `codex-companion task [--fresh] --reviewer <op>`, reject every other argv (bare `["codex"]` included) as a binding shape error naming the expected form, and nix-config's own reviews run on that shape.

**Architecture:** The companion runtime report is already delivered (commit 3bfc93a, kept as is). Commits 55e56aa and 8de63b2 left a two-shape classifier in the skill and in the shared caller paragraph. This plan revises both to the companion shape only (Tasks 1–2), rewrites the evals (Task 3), and migrates the committed contract and the fixtures that copy it, ending in the final gate (Task 4).

**Tech stack:** Markdown skill text; JSON evals and project contract; Python `unittest` contract, resolver and conformance tests; Nix build.

Spec: [2026-10-02-issue-236-companion-review-binding-design.md](../specs/2026-10-02-issue-236-companion-review-binding-design.md). It owns the issue's single decision ledger. This plan rests on D3, D4, D6, D8, D12–D16, and planning added D17–D18. It supersedes [2026-10-02-issue-236-companion-review-binding.md](2026-10-02-issue-236-companion-review-binding.md), whose Task 1 stays delivered.

## Global Constraints

- The one supported shape: basename of `argv[0]` exactly `codex-companion`, `argv[1]` `task`, remaining tokens exactly `--reviewer <op>` plus optional `--fresh` in any order, `<op>` equal to the running operation (per D13).
- Expected form, spelled exactly: `codex-companion task [--fresh] --reviewer <op>` (per D13).
- Companion tail, exactly: `--model gpt-6-astra --effort xhigh --cwd <absolute-worktree> --json`. Packet on stdin, no positional argument, foreground (per D4).
- Validation: exit 0; exactly one JSON object; `status` `0`; `touchedFiles` empty; `runtime.model` `gpt-6-astra`; `runtime.reasoningEffort` `xhigh`; `rawOutput` a non-empty string, the companion's last captured agent message; then operation headings (per D6, D15).
- A binding shape error makes no Codex call, no retry and no native fallback, carries no capability repair ID, and is not a fourth failure class (per D3, D8).
- No exec text survives in the skill, the two caller paragraphs or the evals: no `exec --sandbox`, `--output-last-message`, `terminal agent-message`, `model_reasoning_effort` or JSONL candidate (per D12, D17).
- Out of scope: the patch and `lib/agent-plugins.nix` (do not re-do Task 1 of the superseded plan), `PLAN-REVIEW.md`, `DIFF-REVIEW.md`, the resolver schema, the `codex:codex-reviewer` bridge, nodocom and every other project's bindings, archived records under `.agents/artifacts/` that mention `codex-review`, and `tests/test_agent_costs.py` (it names no review binding).
- `.agents/project.json` is edited only as the authored contract (Task 4); policy is read back only through `resolve-project` (bootstrap).
- Commits are SSH-signed; never disable signing. End each commit with the session's `Co-Authored-By` / `Claude-Session` trailer lines.

## Test seams

- Skill contract tests: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, its ordered-anchor helpers `assert_codex_operation_pair` and `assert_configured_code_review_pair`, and the evals tests (per D16, D17).
- Resolver and conformance suites: `test_resolve_project.py` (including the one committed-bindings snapshot case, per D18), `conformance_test_support.py`, `test_conformance_checks.py` (per D16).
- `just build` and `just agent-workflow-tests`.

## Delivery estimate and boundaries

Estimate: 9 changed files, all small text edits (the largest is the contract test module, about +60/−50 lines). No aggregate-growth risk; the patch is untouched. One deliverable: Tasks 1–3 leave nix-config's own `["codex"]` binding a shape error until Task 4 lands, so no slice ships alone.

## Task index

Task 1 — Skill: companion-only classifier, invocation, validation and shape error — `home/common/claude-code/skills/codex-collaboration/SKILL.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-1.md](2026-10-02-issue-236-companion-only-review.tasks/task-1.md)

Task 2 — Shared caller paragraph, companion-only — `home/common/agent-skills/skills/sdd/final-review.md`, `home/common/agent-skills/skills/ship-issue/REVIEW.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-2.md](2026-10-02-issue-236-companion-only-review.tasks/task-2.md)

Task 3 — Evals describe the companion invocation only — `home/common/claude-code/skills/codex-collaboration/evals/evals.json`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — low-risk — [task-3.md](2026-10-02-issue-236-companion-only-review.tasks/task-3.md)

Task 4 — Migrate nix-config's review bindings and fixtures; final gate — `.agents/project.json`, `home/common/agent-skills/tests/test_resolve_project.py`, `home/common/agent-skills/tests/conformance_test_support.py`, `home/common/agent-skills/tests/test_conformance_checks.py` — full — [task-4.md](2026-10-02-issue-236-companion-only-review.tasks/task-4.md)

## Decisions

Tasks cite the spec's ledger. D12–D16 (the redo) govern; D3, D4, D6 and D8 stand as amended. Planning added D17 (exec pins are replaced and inverted into negative pins) and D18 (the committed-bindings case lives in the resolver suite and asserts bindings, not capability state).

## Acceptance evidence

The patched companion's node suite passes `runtime.reasoningEffort` only because the fake-codex fixture echoes `config.model_reasoning_effort`; it cannot catch a real app-server that ignores `config`. The live companion plan-review and diff-review demo on this repo's migrated bindings (issue acceptance criteria 1–3) is therefore the only real check of runtime attestation. The delivery report must say whether it ran, and if it did not, that attestation is unverified. Precondition (per D19): the installed `codex-companion` and skill are the pre-branch `.p12` build until the user activates this configuration, so the demo runs against this build's closure companion (task-4 Step 8), never the PATH one; and every Codex review of this branch before activation (sdd final review, ship-issue review) is expected to fail validation and take its single native fallback, which the delivery report records as expected rather than as a defect.

## Standards review provenance

- Reviewer: Claude (reviewer agent, Opus), native route taken directly. The configured binding at the reviewed HEAD is still `["codex"]` (the exec route), which this run's first plan review showed cannot pass metadata validation on codex-cli 0.159.0 (no runtime-selection event); a re-run could not establish a Codex review, so no Codex call was made.
- Base SHA 8836b641551b1ab6f2662379f0c0b83e38f5a0fb; reviewed plan commit 6fe2fa2; isolated, read-only.
- Findings: 0 Blocking; 2 Should fix accepted (S1 → D19, `## Acceptance evidence` precondition and task-4 Step 8 build-closure demo; S2 → task-2 caller paragraph states the `argv[0]` basename rule, with an anchor); 3 Discussion: Q1 accepted (first failing condition, in order, names the cause), Q2 accepted (spec test-seams item 1 now points at D18), Q3 informational (clean sweeps). Accepted 4, rejected 0, deferred 0.
