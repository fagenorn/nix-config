# Impeccable Skill Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Both agents get the pinned Impeccable skill, with its detector engine on PATH from a pinned prebuilt binary, and ui-ux-pro-max is retired without deleting user content.

**Architecture:** A new `lib/impeccable.nix` (beside `lib/agent-plugins.nix`) turns the tag-pinned `impeccable` input plus a per-system `fetchurl` engine into one derived skill tree and a `~/.agents/bin/impeccable` wrapper (Task 1). `home/common/agent-skills/default.nix` links that tree to both agents, then drops ui-ux-pro-max and adds a warn-only retired-skill report (Task 2). CLAUDE.md's prose follows (Task 3).

**Tech stack:** Nix flakes (non-flake input, `pkgs.fetchurl`, `runCommand`, `writeShellScript`), Home Manager `home.file` / `home.activation`, Python `unittest` at the installed-home seam.

Spec: [2026-10-02-issue-238-impeccable-design.md](../specs/2026-10-02-issue-238-impeccable-design.md). It owns the issue's single decision ledger, D1–D9.

## Global Constraints

- Upstream: `github:pbakaus/impeccable`, tag `skill-v4.5.0`, `flake = false`; skill tree at `.claude/skills/impeccable`; its `scripts/VERSION` is `0.1.11` (per D1, D2).
- Engine release `engine-v0.1.11`, asset `impeccable-<slot>`; slots `aarch64-darwin` → `darwin-arm64`, `x86_64-linux` → `linux-x64`; SRI hashes (from the `.sha256` sidecars) `sha256-dCeRjW51UHQBobe2ke7+WKfAGi/GO3EgFv/FoKwcBeY=` (darwin-arm64) and `sha256-AiFgfh9TWvk36iZ8NHsfkCM7hdwlY8vS7u/fQuDlxZQ=` (linux-x64).
- `flake.lock` changes only through `nix flake lock` (never `just update`); no other input's node may change.
- Upstream files are copied unmodified; the launcher is never patched (per D3, D4).
- Never switch (per D8). Verification is `just build`, the anis-desktop `nix eval` CI runs, and `just agent-installed-skill-tests`.
- Out of scope: wiring Impeccable into `sdd`/`from-issue`, other engine platforms, building the engine from source, generalising `migrateCodexSkillLinks`, editing historical specs/plans.
- Commits are SSH-signed (never disable signing) and end with the session's `Co-Authored-By` / `Claude-Session` trailer lines.

## Test seams

- `just build` on mbp, plus `nix eval --raw '.#nixosConfigurations.anis-desktop.config.system.build.toplevel.drvPath'` for Linux (spec seam 1, D2).
- `just agent-installed-skill-tests`, with the new module `tests/test_impeccable_installed.py` (spec seam 2, D7, D9).
- Post-switch manual check, owner-run only (spec seam 3, D8).

## Delivery estimate and boundaries

Estimate: 7 changed files (`flake.nix`, `flake.lock`, `lib/impeccable.nix`, `home/common/agent-skills/default.nix`, `tests/test_impeccable_installed.py`, `justfile`, `CLAUDE.md`), roughly 250 added and 50 removed lines. No aggregate-growth risk; one deliverable. The PR body must record: SKILL.md is 12,115 B and loads only on invocation; the 42 `reference/*.md` playbooks load on demand via SKILL.md's Commands table; the post-switch check result, or "owner-pending" (per D8).

## Task index

Task 1 — Pinned Impeccable tree, engine and wrapper linked to both agents — `flake.nix`, `flake.lock`, `lib/impeccable.nix`, `home/common/agent-skills/default.nix`, `tests/test_impeccable_installed.py`, `justfile` — full — [task-1.md](2026-10-02-issue-238-impeccable.tasks/task-1.md)

Task 2 — Retire ui-ux-pro-max with a warn-only report — `flake.nix`, `flake.lock`, `home/common/agent-skills/default.nix`, `tests/test_impeccable_installed.py` — full — [task-2.md](2026-10-02-issue-238-impeccable.tasks/task-2.md)

Task 3 — Architecture prose — `CLAUDE.md` — low-risk — [task-3.md](2026-10-02-issue-238-impeccable.tasks/task-3.md)

## Decisions

Tasks cite D1–D7 (spec) and D8–D9 (appended by planning) by ID.

## Standards review provenance

Reviewer: Codex (`codex-companion task --fresh --reviewer plan-review`, gpt-6-astra/xhigh), isolated read-only, base 5ad84230. 2 findings accepted (238-B1 Blocking, 238-S1 Should fix, per D10), 0 rejected, 0 deferred. No fallback.
