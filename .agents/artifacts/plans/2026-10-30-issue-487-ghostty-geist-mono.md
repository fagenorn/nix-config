# Ghostty Uses GeistMono Nerd Font Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Ghostty draws the terminal in `GeistMono Nerd Font Mono` on `mbp`, `eleven-m5` and `anis-desktop`, with `nerd-fonts.geist-mono` installed as a system font on all three and FiraCode kept.

**Architecture:** One `fonts.packages = [ pkgs.nerd-fonts.geist-mono ];` in the all-hosts module `hosts/common/common-packages.nix`, which the module system merges with `darwin-common.nix`'s FiraCode list on macOS (D2). Ghostty's `font-family` string becomes the registered Mono family (D1). Nothing is activated: the evidence is evaluation, build and a pre-activation `fc-scan` of the font tree (D3, D4).

**Tech stack:** Nix flakes, nix-darwin, NixOS-WSL, Home Manager (`programs.ghostty`), fontconfig `fc-scan` from the pinned nixpkgs, Just.

Spec: `.agents/artifacts/specs/2026-10-30-issue-487-ghostty-geist-mono-design.md`. A bare "Dn" cites its `## Decision ledger`; this plan appends D6. Issue: https://github.com/fagenorn/nix-config/issues/487.

## Global Constraints

- Base `07f89813` (`origin/main` at planning). Spec commit `fc8eaf04`.
- Code changes only `hosts/common/common-packages.nix` and `home/common/ghostty/default.nix`. Unchanged: `hosts/common/darwin-common.nix`, `hosts/common/linux-common.nix`, the font entries in `environment.systemPackages`, `font-size` and every other Ghostty setting (spec § Out of scope).
- Family string, verbatim: `GeistMono Nerd Font Mono` (D1). Package: `pkgs.nerd-fonts.geist-mono`, named `nerd-fonts-geist-mono-3.4.0+1.401` at the pinned lock (D2).
- Never run `just switch`, `darwin-rebuild`, `nixos-rebuild switch`, `just update` or `nix flake update`, and never write `/Library/Fonts` (D3). The post-switch checks are the owner's.
- `anis-desktop`'s `config.fonts.packages` evaluates on this darwin host (measured at `fc8eaf04`). Its toplevel is CI `Nix Eval`'s; do not evaluate it locally.
- Comments describe the code as it behaves at the task's commit. Commit subjects end `(issue 487)`.
- Run every long command in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>`, with an explicit timeout above its duration. Commit through `launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <git commit args>`; commits are SSH-signed and end with the session's trailer lines. Scratch files go under the root that `launch-scope scratch` prints. Never push.
- Timeouts: the gate script 1800 s; `just build mbp` 3600 s; the `eleven-m5` drvPath eval 900 s.
- Final gate (sdd runs it once, on the final head): `just build` (`nix-build`). `agent-workflow-tests` is skipped: "no agent-tooling paths changed".

## Test seams

- Host evaluation (spec § Test seams, D4, D6): `nix eval` of `mbp`'s `programs.ghostty.settings.font-family` and of each host's `config.fonts.packages` names, plus the built `ghostty/config` file. All of these run in the task's gate script.
- Build: `just build mbp`, and the `eleven-m5` toplevel drvPath eval. CI `Nix Eval` covers `anis-desktop`.
- Pre-activation font proof (D3): the pinned `fc-scan` over `mbp`'s `system.build.fonts` tree.
- Owner, after `just switch` on `mbp` and a Ghostty relaunch: the literal AC3 command and AC4.

## Delivery estimate and boundaries

Estimate: two code files, +4/−1 lines (a planning trial measured exactly that), plus the acceptance record (about 2 KB). One review package, no aggregate-growth risk, no split.

## Task index

Task 1 — Install GeistMono Nerd Font on every host and name it in Ghostty — `hosts/common/common-packages.nix`, `home/common/ghostty/default.nix`, `.agents/artifacts/plans/2026-10-30-issue-487-ghostty-geist-mono.acceptance.md` — low-risk — [task-1.md](2026-10-30-issue-487-ghostty-geist-mono.tasks/task-1.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 1 | The gate script's three `AC1` lines at the code commit: `AC1 font-family head: GeistMono Nerd Font Mono` (D4's `nix eval --raw … --apply builtins.head`), `AC1 font-family: ["GeistMono Nerd Font Mono"]` and `AC1 ghostty/config: as expected` (D6). Also `just build mbp` in Step 5 and `just build` in sdd's final verification. |
| AC2 | code | Task 1 | The gate script's three `AC2` lines at the code commit, each host's sorted `fonts.packages` names equal to the expected list (D6). Also the PR's CI `Nix Eval` of `anis-desktop` at ship time. |
| AC3 | evidence | Task 1 | The pre-activation proxy (D3): the gate script's `AC3 proxy` line at the code commit, from the pinned `fc-scan` over `mbp`'s `system.build.fonts` tree. Threshold: ≥ 1 file whose family list holds exactly `GeistMono Nerd Font Mono`. Conditions: `mbp`, before activation, no `just switch`. Acceptance-record row `AC3`. The literal `ghostty +list-fonts \| grep -cF "GeistMono Nerd Font Mono"` ≥ 1, after `just switch` on `mbp` with Ghostty relaunched, is the owner's. |
| AC4 | human | Task 1 | The owner, on `mbp` after `just switch` and a Ghostty relaunch: a fresh Ghostty window renders Geist Mono, with no missing-glyph boxes in the starship prompt or in Helix's file-picker icons. |

## Decisions

- Task 1 rests on D1 to D4 and D6. D5 governs the ship-time sync with #486. Planning appended D6, which pins exact values in the gate.
- The plan has one task, not a font task followed by a Ghostty task. `verified-tree fresh` marks a row stale when any file other than the record changes after the row's `Commit`, so every row is measured at the single code commit.
- Planning trial: at `fc8eaf04`, in a scratch worktree that was then discarded. Before the edits, the gate script exited 1 with Task 1 Step 2's lines; the FiraCode calibration count was 6. With the edits it exited 0 and the proxy counted 9. `just build` exited 0 in 76 s, the `eleven-m5` drvPath eval exited 0, and `nixfmt --check` passed on both files.

## Standards review provenance

- Reviewer: Codex (`codex-plan-review`, gpt-6-astra, xhigh), isolated read-only mode, no focus. No fallback.
- Base `07f89813`; reviewed plan commit `f7382869`.
- Findings: Blocking none, Should fix none, Discussion one (unknowns only: the reviewer ran no evaluations; AC3's literal check and AC4 stay the owner's per D3). Accepted 0, rejected 0, deferred 0.

---
