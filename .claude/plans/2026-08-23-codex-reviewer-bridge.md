# Codex Reviewer Bridge Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Give the Claude→Codex reviewer bridge a per-operation reviewer budget with a transport ceiling that provably covers it, guarantee `~/.agents/bin` on every reviewer subprocess PATH from the repo-owned wrapper, and stop the read-only sandbox's own limits from arriving as review findings — per the spec `.claude/specs/2026-08-23-codex-reviewer-bridge-design.md` (issue fagenorn/nix-config#104).

**Architecture:** A new importable runtime module in the patched plugin — the reviewer operation registry — becomes the single home for which review operations exist and what each may spend (`plan-review` 1 680 000 ms, `diff-review` 840 000 ms); the CLI entrypoint derives both its closed operation set and its default budget from it, and the transport agent definition stops naming any worker-side budget, waiting a uniform four bounded 540 s calls instead. The PATH guarantee is constructed one line up from the plugin, in the repo-owned `codex-companion` wrapper. The read-only boundary is stated once in the shared rubric's packet-borne read-only rules, and both packets stop handing the reviewer verification it is forbidden to perform.

**Tech stack:** Node.js ESM + `node:test` inside a scratch clone of the pinned `openai/codex-plugin-cc` tree; Nix (patch derivation in `lib/agent-plugins.nix`, `writeShellScriptBin` wrapper in `home/common/claude-code/default.nix`); Markdown rubric prose under a Python 3 `unittest` contract suite.

## Global Constraints

- Reviewer budgets are exactly `plan-review` 1 680 000 ms and `diff-review` 840 000 ms; the closed operation set is derived from the registry's keys, an explicit `--timeout-ms` still overrides, and non-reviewer tasks still default to no bound (per D1, D2).
- After this plan the transport agent definition contains **zero** worker-side budget claims and no `840`; it keeps only its own numbers — the 540 000 ms per-call bound, the Bash tool's 600 000 ms cap, and the 2160 s ceiling it measures itself (per D3).
- The isolation model is untouched: fresh `CODEX_HOME`, approval policy `never`, sandbox `read-only`. No writable roots, no network, no shared broker (per D6).
- Plugin edits happen in **one** scratch clone of pinned rev `db52e28f4d9ded852ab3942cea316258ae4ef346` (the `codex-plugin-cc` input in `flake.nix`), applied with `git apply --unidiff-zero`, regenerated **once** with `git diff -U0 <pin>`, with `patchRevision` in `lib/agent-plugins.nix` bumped 10→11 exactly once, subject to the D10 collision re-check.
- Never `grep` the patch text to assert anything about the patched source: a zero-context patch carries no per-line file attribution. Read the scratch clone or the built store path (CLAUDE.md; per D10).
- The plugin suite is invoked only as `env -u CLAUDE_PLUGIN_DATA -u CODEX_COMPANION_SESSION_ID -u CODEX_COMPANION_TRANSCRIPT_PATH node --test tests/*.test.mjs` from the scratch clone root; unscrubbed, four upstream tests fail spuriously (CLAUDE.md).
- Add no dependency anywhere. The plugin tree is node built-ins only; the repo suites are Python 3 stdlib only.
- Nix-side verification is `just build`. There is no unit-test suite for the Nix configs, and no task runs `just switch` or deploys.
- Every commit is SSH-signed as configured — never pass `-c commit.gpgsign=false` or `--no-gpg-sign`; surface a signing failure instead of working around it. Every commit message ends with `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- Run every command from the worktree root `/Users/anis/tmp/nix-config/.claude/worktrees/worktree-issue-104` unless a step says otherwise.

## Test seams

- **Per-operation budget → the enqueued job record.** `tests/reviewer-detach.test.mjs`'s existing both-operations loop asserts the stored `request.timeoutMs`; `tests/worker-postmortem.test.mjs`'s existing both-operations deadline test asserts `deadlineAt − createdAt`. Both read the registry (per D9, D12).
- **Transport contract → `tests/commands.test.mjs`.** The existing agent-definition test gains the positive wait-count/ceiling pins and the negative "no worker-side budget claim" assertion; a second test in the same file carries the ceiling invariant, importing the registry (per D3, D9, D11, D13).
- **Rubric contracts → `home/common/agent-skills/tests/test_workflow_skill_contracts.py`**, run by `just agent-workflow-tests`. It already loads all four collaboration rubric files; it gains the per-operation wall-clock pins, the sandbox-limits rule, the packet reframing in both packets, and the eval restatement (per D8, D14, D15).
- **Built-artifact confirmation** — `just build`, then read values out of the discovered store path (`nix-store --query --requisites ./result | grep -- '<suffix>$'`, requiring exactly one match, the `just show-claude-settings` idiom). Never the patch text.

No other seams. A task needing a new one is a plan bug.

**Deliberately not seams.** A live reviewer probe and the post-ship kill-rate survey both require an activated build (`just switch`) and plan-reviews accumulated on it; the spec places both outside this branch's verification. The collaboration skill's evals are prose fixtures graded by hand against a model — this plan pins their *text* (per D15) and claims nothing about their outcome.

## Task index

Task 1 — Reviewer operation registry, per-operation budget, transport wait ceiling — `patches/agent-plugins/codex-plugin-cc.patch`, `lib/agent-plugins.nix` — full — [task-1.md](2026-08-23-codex-reviewer-bridge.tasks/task-1.md)
Task 2 — `~/.agents/bin` guaranteed on the reviewer subprocess PATH — `home/common/claude-code/default.nix` — low-risk — [task-2.md](2026-08-23-codex-reviewer-bridge.tasks/task-2.md)
Task 3 — Sandbox limits are not findings; per-operation wall clock — `home/common/claude-code/skills/codex-collaboration/{SKILL.md,PLAN-REVIEW.md,DIFF-REVIEW.md,evals/evals.json}`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-3.md](2026-08-23-codex-reviewer-bridge.tasks/task-3.md)

Order: 1 → 3 (Task 3's caller-facing sentence states the wall clock Task 1's registry makes true). Task 2 is independent of both and may run at any point.

## Decisions

The spec owns the single decision ledger (D1–D15). Tasks cite rows inline; planning appended D12–D15 — the sixth coupled patch file and the seam-1 split, the machine-readable wait-count phrasing, the read-only rule's placement in the packet-borne rules, and pinning both wall-clock restatements.

Two corrections this plan inherits from the ledger rather than from the spec's prose: the patch moves **six** files, not the five the spec's *Patch workflow* paragraph names (per D12), and the read-only rule lands in `## Read-only rules (both operations)`, not in the Launch paragraph the *Decisions* section pointed at (per D14).

---
