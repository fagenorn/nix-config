# Codex Ship Handoff Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Scope `ship-issue`'s no-re-prompt claim to the host enforcement model and route the review-adjudicated host through one consolidated operator gate that resumes to issue closure.

**Architecture:** Three prose surfaces inside the machine-global skills tree change, in dependency order. A new `ship-issue` sidecar `HUMAN-GATE.md` owns the gate (per D4), so it lands first and nothing ever links to a missing file. `ship-issue/SKILL.md` then splits its `## Standing authorization` second sentence into two host-enforcement-model rows and adds two one-line phase pointers. `from-issue/AUTO.md` takes two amendments: its final paragraph gains one case in its enumeration so the gate reuses the existing `blocked_on: human_gate` suspension rather than defining a second pause, and its general self-answer sentence gains an exemption for irreversible-authorization gates, which `--auto` must never answer on the operator's behalf (per D13). Every change is contract prose pinned by the existing Python contract suite; no Nix, no scripts, no host detection.

**Tech stack:** Markdown skill contracts under `home/common/agent-skills/skills/`; Python `unittest` prose assertions in `home/common/agent-skills/tests/test_workflow_skill_contracts.py`; Nix home-manager materialization via `home/common/agent-skills/default.nix`.

## Global Constraints

- Out of scope, never edit: `home/common/claude-code/default.nix`, `tests/test_claude_permission_guard.py`, `home/common/agent-skills/skills/ship-release/SKILL.md` (per D9), root `AGENTS.md` and `.agents/instructions/bootstrap.md` (per D3).
- `home/common/agent-skills/README.md`'s `## Host adapter accommodations` section is **already written** at the base commit by the design phase (per D1). No task recreates, reworders or pins it; Task 3 verifies it only.
- The path is selected by the host's stated *enforcement model*, never by detecting the host: no environment-variable sniffing, no probe command, no capability handshake (per D3).
- No auto-grant of any kind: no inference of a grant from a prior turn, label, config key, environment variable or previous run, and no retry loop that converges on approval.
- The literal string `gh pr merge` must never appear in `HUMAN-GATE.md`, and no *new* line in `ship-issue/SKILL.md` may contain it (per D6, D10). Phase 7 stays the single authoritative home for that spelling.
- `home/common/agent-skills/default.nix` links whole skill directories (`lib.filterAttrs (_: type: type == "directory") (builtins.readDir ./skills)` → `source = ./skills + "/${name}"`), so it carries **no per-file manifest**. A new sidecar needs no Nix change; Task 3's `just build` confirms it.
- Commit messages append, verbatim:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_0128oBTKhwUFwSefRhxX2PAy
  ```
  Commits are SSH-signed; never pass `-c commit.gpgsign=false` or `--no-gpg-sign`. Surface a signing failure rather than working around it.
- Every `gh` invocation must pass `--repo fagenorn/nix-config` — an `upstream` remote points at `ironicbadger/nix-config` and bare `gh` resolves there.

## Test seams

- `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — the one contract-prose seam. No new seam is introduced. Run from the worktree root: `python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py`. **`pytest` is not installed on this machine** — the suite is a plain `unittest` module and is run by invoking the file directly. A single test: `python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py WorkflowSkillContractsTest.<test_name> -v`. The whole agent-workflow suite: `just agent-workflow-tests`.
- New sidecar files are pinned by a module-level path constant read once in `setUpClass`, following the existing `SHIP_ISSUE_REVIEW` / `cls.ship_review` precedent.
- `just build` validates that the skills tree still evaluates and materializes. There is no Nix unit-test suite.
- The `## Host adapter accommodations` README record is deliberately **not** pinned by a test (per D1) — the behaviour it describes is pinned in the two skill files instead.

## Task index

Task 1 — Add the `HUMAN-GATE.md` consolidated operator gate — `home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-1.md](2026-09-02-codex-ship-handoff.tasks/task-1.md)
Task 2 — Scope the standing-authorization claim per host enforcement model — `home/common/agent-skills/skills/ship-issue/SKILL.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-2.md](2026-09-02-codex-ship-handoff.tasks/task-2.md)
Task 3 — Extend the `--auto` gate enumeration and verify the accommodation record — `home/common/agent-skills/skills/from-issue/AUTO.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-3.md](2026-09-02-codex-ship-handoff.tasks/task-3.md)

## Decisions

The single issue-level ledger lives in `.claude/specs/2026-09-02-codex-ship-handoff-design.md` under `## Decision ledger`. This plan cites it by ID and never restates a row.

- Task 1 rests on D2 (two gates, forced by the unknown `<pr-num>` at Phase 4), D4 (sidecar, not inline), D5 (the term is *operator gate* / *human gate*), D6 (the merge is never re-spelled outside Phase 7), D7 (enter the gate instead of attempting the verb), D8 (the grant is additional to every existing check), D14 (the no-bypass list is pinned section-scoped), D15 (the command payloads are pinned, not left to the implementer) and D16 (two *planned* gate locations, not a hard entry count).
- Task 2 rests on D3 (enforcement model as prose rows, no host detection) and D6 (the pinned exact-ordered `gh pr merge` list stays at three entries, one changed), plus D10, D12 (Phase-7 order is Gate 2 → `check-launch` → merge) and D15 (the whole `## Standing authorization` section is pinned by equality).
- Task 3 rests on D1 (the README record is the accommodation store and is not test-pinned), D9 (`ship-release` deliberately unamended), D11, D13 (`AUTO.md`'s self-answer exemption) and D14 (AC3 is a section-scoped Python assertion, not a line-local `grep`).
- Planning appended **D10** and **D11** to the spec's ledger; the Phase-5 standards review appended **D12**–**D16**.

## Standards review provenance

- Reviewer: `Codex`, isolated read-only mode. No fallback reviewer was used.
- Base SHA: `25d9989fd12c8a701a63cf2ac669f6d48e72b539`; HEAD reviewed: `0c5c655fc9d2a809fb9b1bd323e23c2c5e1299aa`.
- Focus: none configured.
- Dispositions: 3 blocking accepted, 2 should-fix accepted, 1 discussion accepted; 0 rejected, 0 deferred.
- Applied as plan edits in this commit; the reasoning is carried by ledger rows **D12**–**D16** in `.claude/specs/2026-09-02-codex-ship-handoff-design.md`. The raw reviewer transcript is deliberately not stored — this summary is the whole record.
