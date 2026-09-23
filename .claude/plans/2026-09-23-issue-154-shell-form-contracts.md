# Shell-Form Contracts Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Shared-skill shell examples stop teaching the four forms the worktree
isolation checker refuses, the `worktrees` skill states the checker contract,
and one classifier holds source trees, installed trees and fixtures to it
([#154](https://github.com/fagenorn/nix-config/issues/154)).

**Architecture:** A support module takes over the skill-tree and installed-view
layout from `test_dispatch_contracts.py` (Task 1). A new contract module,
`test_shell_example_contracts.py`, owns the one public classifier
`refused_examples(document_text)`, its fixtures and the vocabulary guard, and the
`worktrees` probe is rewritten so the fixture host is clean (Task 2). The
`worktrees` guidance section follows (Task 3), then the from-issue/ship-issue
rewrites (Task 4), the ship-release rewrites together with the source sweep
(Task 5), and last the installed sweep and its recipe (Task 6).

**Tech stack:** Python 3 `unittest` (stdlib only; CI's Ubuntu 24.04 Python
3.12), Markdown skill prose, `just`, Nix (`just build`).

Spec (source of truth, read whole):
`.claude/specs/2026-09-23-issue-154-shell-form-contracts-design.md`, D1–D21.

## Global Constraints

- Swept documents: every `*.md` under `home/common/agent-skills/skills` and
  `home/common/claude-code/skills` whose path below the tree has no `evals`
  component (per D1).
- Refused forms, closed: `chain`, `pipe`, `redirect`, `heredoc`, `unparseable`
  (per D4). Command substitution is not a form (per D8).
- The one sanctioned chain is the guard's literal, read from the single
  `UNSET_GITHUB_TOKEN_PREFIX = "…"` assignment in
  `home/common/claude-code/default.nix`; never restated in a test, never
  replaced by `env -u GITHUB_TOKEN` (per D5).
- Every rewrite keeps the example's meaning (per D7); existing `$(…)` sites
  stay (per D8); no exemption list anywhere (per D9, D20).
- Retained branch `worktree-issue-99-skill-prose-fixes` stays read-only at
  `3c9709ca470bd473d49b39a611ca6cab258973db`: read it only with
  `git show 3c9709ca:<path>` or `git diff 95b6caf 3c9709ca -- <path>`; never
  check out, cherry-pick, merge, rebase or add a worktree for it (per D15).
- A commit that lands a recovered or adapted hunk (Tasks 2, 3, 4, 5) lists
  those hunks in its body and carries
  `Recovered-From: 3c9709ca470bd473d49b39a611ca6cab258973db` in the same final
  trailer paragraph as the attribution lines; Tasks 1 and 6 carry none (per D15).
- Out of scope, never added: `env -u GITHUB_TOKEN`, any
  `.claude/skills.config.json` "if it exists" wording, leaf-agent clauses,
  `writing-plans` edits, `.nix`, CI, `CLAUDE.md`, ADR or `docs/` changes, the
  permission-guard suite (per D5, D16, D17).
- Commits are SSH-signed (never disable signing) and end with the attribution
  trailer lines the executing harness prescribes.
- Every task leaves `just agent-workflow-tests` green (per D20).
- Verification commands in this plan are single plain commands: no chain,
  pipe, redirect or heredoc — the shapes this issue removes.

## Test seams

- `home/common/agent-skills/tests/test_shell_example_contracts.py` only (D3,
  D16): public boundary `refused_examples(document_text) -> tuple[Finding, ...]`
  plus `FORMS`, `COMMAND_VOCABULARY`, `SANCTIONED_PREFIX`, `shell_fence_heads`
  and `swept_documents` (D14, D19).
- Classes: `RefusedFormFixtureTest`, `SanctionedPrefixTest`,
  `VocabularyGuardTest`, `WorktreesGuidanceTest`, `SourceTreeSweepTest`,
  `InstalledTreeSweepTest` (D13, D18, D21).
- Installed trees enter only through `AGENT_SKILLS_INSTALLED_HOME`, laid out by
  `home/common/agent-skills/tests/skill_tree_support.py` (D13).
- Existing pins adjusted in place: `test_workflow_skill_contracts.py` Gate 1
  anchor (D11), `test_ship_release_contracts.py` PREV_TAG execution (D12).

## Delivery estimate and boundaries

Estimate: 14 product files — 2 new test modules (~60 and ~420 lines), 3
modified test modules (~40 lines net), `justfile` (2 lines), 8 skill documents
(~60 lines net). One review package; no slice exceeds the gate. Tasks are
sequential: each consumes the previous one's module state.

## Task index

Task 1 — Skill-tree support module — `home/common/agent-skills/tests/skill_tree_support.py` (create), `home/common/agent-skills/tests/test_dispatch_contracts.py` — low-risk — [task-1.md](2026-09-23-issue-154-shell-form-contracts.tasks/task-1.md)

Task 2 — Classifier, fixtures, vocabulary guard and isolation probe — `home/common/agent-skills/tests/test_shell_example_contracts.py` (create), `justfile`, `worktrees/SKILL.md` — full — [task-2.md](2026-09-23-issue-154-shell-form-contracts.tasks/task-2.md)

Task 3 — Checker-contract guidance — `worktrees/SKILL.md`, `test_shell_example_contracts.py` — full — [task-3.md](2026-09-23-issue-154-shell-form-contracts.tasks/task-3.md)

Task 4 — from-issue and ship-issue rewrites — `from-issue/SKILL.md`, `ship-issue/{SKILL,HUMAN-GATE,CI-MERGE,SYNC}.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-4.md](2026-09-23-issue-154-shell-form-contracts.tasks/task-4.md)

Task 5 — ship-release rewrites and the source sweep — `ship-release/{SKILL,CHANGELOG}.md`, `home/common/agent-skills/tests/test_ship_release_contracts.py`, `test_shell_example_contracts.py` — full — [task-5.md](2026-09-23-issue-154-shell-form-contracts.tasks/task-5.md)

Task 6 — Installed sweep and recipe — `test_shell_example_contracts.py`, `justfile` — low-risk — [task-6.md](2026-09-23-issue-154-shell-form-contracts.tasks/task-6.md)

(Skill paths without a prefix are under `home/common/agent-skills/skills/`; a
bare `test_shell_example_contracts.py` is under `home/common/agent-skills/tests/`.)

## Decisions

The spec's `## Decision ledger` is authoritative. Tasks cite D1–D18 from design
and the three rows planning added: D19 (per-call examples, finding lines, the
fixed vocabulary), D20 (the source sweep lands with the last rewrite; earlier
rewrites gate on the classifier directly) and D21 (per-operator fixtures and
the heredoc-body control).

---
