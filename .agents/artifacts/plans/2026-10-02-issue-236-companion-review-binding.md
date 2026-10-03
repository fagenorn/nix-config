> **Superseded** by [2026-10-02-issue-236-companion-only-review.md](2026-10-02-issue-236-companion-only-review.md) (companion-only redo, spec D12–D18); its Task 1 (commit 3bfc93a) stays delivered.

# Companion Review Binding Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** A configured Codex review on a `codex-companion task --reviewer <op>` binding delivers its packet on stdin, is validated against a runtime selection the companion reports, and any binding the skill cannot drive stops as a named binding shape error with no native fallback.

**Architecture:** The patched companion learns to report `runtime: {model, reasoningEffort}` from the app-server's thread response (Task 1). `codex-collaboration` classifies the authored argv into a closed set of two review binding shapes and gives each its own invocation and validation (Task 2). The configured-review paragraph that two callers share is rewritten in step (Task 3), and the evals describe both shapes (Task 4).

**Tech stack:** Markdown skill text; Python `unittest` contract tests; Node ESM (stdlib only) for the patched `codex-plugin-cc`; Nix (`lib/agent-plugins.nix`).

Spec: [2026-10-02-issue-236-companion-review-binding-design.md](../specs/2026-10-02-issue-236-companion-review-binding-design.md). It owns the issue's single decision ledger, D1–D10.

## Global Constraints

- Model `gpt-6-astra` and reasoning effort `xhigh` on both shapes. These are the exact values in the existing exec tail.
- The exec shape's tail, its JSONL and last-message candidates, and its validation stay byte-for-byte as they are today (per D1).
- The companion tail is exactly `--model gpt-6-astra --effort xhigh --cwd <absolute-worktree> --json`. The packet goes on stdin with no positional argument, and the call runs in the foreground (per D4).
- The binding shape error is a pre-call configuration stop. It is not a fourth Codex failure class: `DIFF-REVIEW.md`'s "closed list of three" must stay true (per D3, D8).
- Patch edits follow CLAUDE.md exactly. Work in a scratch clone of the pinned rev `db52e28f4d9ded852ab3942cea316258ae4ef346`, apply with `git apply --unidiff-zero`, regenerate with `git diff -U0 db52e28f4d9ded852ab3942cea316258ae4ef346`, bump `patchRevision` 12 → 13, and run the suite as `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/*.test.mjs`. Never grep the patch text to assert something about the source.
- Out of scope: `PLAN-REVIEW.md`, `DIFF-REVIEW.md` (neither restates the invocation or the validation), the resolver schema, the `codex:codex-reviewer` bridge, and every project's authored bindings.
- Repository commits are SSH-signed. Never disable signing. End each commit with the session's `Co-Authored-By` / `Claude-Session` trailer lines.

## Test seams

- Skill contract tests: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, extending `assert_codex_operation_pair`, `assert_configured_code_review_pair` and the evals tests (per D7).
- Companion node suite: `tests/reviewer-detach.test.mjs` in the scratch clone, with the existing fake-codex fixture (per D7).
- `just build`, which proves the patch applies and installs the edited skill text (per D7).

## Delivery estimate and boundaries

Estimate: 8 changed files. One is the regenerated patch, which is large (about 250 KB) and grows by about 2 KB. Its size is the main aggregate-growth risk for a review package. Tasks 2–4 depend on Task 1 being in place only for the truth of the `runtime` sentences, not to build. The plan is one deliverable; no slice ships on its own.

## Task index

Task 1 — Companion runtime report — `patches/agent-plugins/codex-plugin-cc.patch`, `lib/agent-plugins.nix` — full — [task-1.md](2026-10-02-issue-236-companion-review-binding.tasks/task-1.md)

Task 2 — Skill binding-shape classifier, companion invocation and validation — `home/common/claude-code/skills/codex-collaboration/SKILL.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-2.md](2026-10-02-issue-236-companion-review-binding.tasks/task-2.md)

Task 3 — Shared caller configured-review paragraph — `home/common/agent-skills/skills/sdd/final-review.md`, `home/common/agent-skills/skills/ship-issue/REVIEW.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-3.md](2026-10-02-issue-236-companion-review-binding.tasks/task-3.md)

Task 4 — Evals describe both shapes; final gate — `home/common/claude-code/skills/codex-collaboration/evals/evals.json`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — low-risk — [task-4.md](2026-10-02-issue-236-companion-review-binding.tasks/task-4.md)

## Decisions

Tasks cite the spec's ledger: D1–D8 come from design, and planning added D9 (the caller paragraph copies) and D10 (`thread/start` config only when an effort is requested), and standards review added D11 (the exec shape's known attestation gap, out of scope).

## Acceptance evidence

The node suite's `runtime.reasoningEffort` assertion passes because the fake-codex fixture echoes `config.model_reasoning_effort`; it cannot catch a real app-server that ignores `config`. The live companion plan-review and diff-review demo (issue acceptance criteria 1–3) is therefore the only real check of the runtime attestation, and the delivery report must say whether it ran.

## Standards review provenance

- Reviewer: Claude fallback (reviewer agent, Opus). The configured Codex plan-review (`codex-review` → `codex exec`, codex-cli 0.159.0) completed with exit 0 but failed metadata validation: no runtime-selection event naming model/effort (per D11). One native fallback with the same packet, plus that observation; no Codex retry.
- Base SHA 8836b641551b1ab6f2662379f0c0b83e38f5a0fb; reviewed plan commit 9834b6d; isolated, read-only.
- Findings: 0 Blocking; 3 Should fix accepted (S1 → D11 and corrected D5 grounding; S2 → "last captured agent message" wording in Tasks 2–4 and D6; S3 → Task 1 store path taken from this build's closure); 2 Discussion: D2 accepted as the acceptance-evidence note above; D1 (how a companion capacity rejection is recognised) deferred: the shared failure-class paragraph stays unchanged per D8 and stays true, and the reviewer runtime is a per-job isolated runtime (`lib/codex.mjs` `createReviewerRuntime`), so no new capacity signal is defined here. Accepted 4, rejected 0, deferred 1.
