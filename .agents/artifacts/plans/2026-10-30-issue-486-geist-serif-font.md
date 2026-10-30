# Geist Serif System Font Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Geist Serif v1.9.0 (Regular, Square, Triangle and Heart) is a system font on `mbp`, `eleven-m5` and `anis-desktop`, and FiraCode stays installed.

**Architecture:** A local `stdenvNoCC` derivation, `lib/geist-serif.nix`, fetches the upstream release zip by its flat hash and unzips four named static TTFs into `share/fonts/truetype` (D1, D3). `hosts/common/common-packages.nix`, which both `mkDarwin` and `mkNixos` load, adds it to `fonts.packages` once. On darwin, that list merges with FiraCode's (D2, D4).

**Tech stack:** Nix (nixpkgs 25.11 `stdenvNoCC`, `fetchurl`, `unzip`), nix-darwin and NixOS `fonts.packages`, Just.

Spec: `.agents/artifacts/specs/2026-10-30-issue-486-geist-serif-font-design.md`. A bare "Dn" cites its `## Decision ledger`. This plan appends D6. Issue: https://github.com/fagenorn/nix-config/issues/486.

## Global Constraints

- Base `07f89813` (`origin/main` at planning). Spec commit `a4428457`.
- Declared verification: `just build`, from `bindings.workflow.verification`. No agent-tooling path changes, so `just agent-workflow-tests` is not declared.
- Not edited: `hosts/common/darwin-common.nix` (FiraCode stays exactly as it is), `hosts/common/linux-common.nix`, `flake.nix`, `lib/helpers.nix`, `CLAUDE.md` and every doc. No overlay, no `pkgs/` tree and no flake `packages` or `checks` output (D1, D5).
- Comments describe the code as it behaves at that task's commit. Write "issue 486", never a bare `#486`. Do not write `TODO` or `FIXME`.
- Run every long command in the foreground from the worktree root, with an explicit timeout above its duration, as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>`. Commit through `launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <git commit args>`. Commits are SSH-signed and end with the session's trailer lines. Scratch files and build out-links go under the root that `launch-scope scratch` prints (`<scratch>` below). **No agent runs `just switch`** (D6), and no agent pushes.
- **Build** (timeout 3600 s): `bash -c 'set -o pipefail; just build 2>&1 | tail -3'`. On mbp it builds `.#darwinConfigurations.mbp.system` and writes the gitignored `./result`.
- Final gate (sdd runs it once, on the final head): the Build run.

## Test seams

These are the spec's § Test seams, and none of them is new:

- Configuration evaluation: `nix eval` of `config.fonts.packages` on each host (AC2, AC3). CI `Nix Eval` evaluates `anis-desktop`'s `toplevel.drvPath`. On mbp that evaluation fails, at base too, because a catppuccin-starship import-from-derivation needs an x86_64-linux builder. So CI is its only full run.
- The system closure: `nix build .#darwinConfigurations.<host>.system` plus `nix-store -qR` (AC1).
- The activated machine: `system_profiler SPFontsDataType` after the owner's `just switch` on mbp (AC4, AC5, D6).

## Delivery estimate and boundaries

All figures are estimates. Two changed files, about +45 lines: `lib/geist-serif.nix` (new, about 40 lines) and `hosts/common/common-packages.nix` (+4 lines). There is one review package and no split.

## Task index

Task 1 — Geist Serif package and all-hosts registration — `lib/geist-serif.nix`, `hosts/common/common-packages.nix` — full — [task-1.md](2026-10-30-issue-486-geist-serif-font.tasks/task-1.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 1 | For `mbp` and `eleven-m5`: `nix build .#darwinConfigurations.<host>.system -o <scratch>/r-<host>`, then `nix-store -qR <scratch>/r-<host> \| xargs -I{} find {} -name GeistSerif-Heart.ttf` prints at least one path per host (Task 1 Step 5) |
| AC2 | code | Task 1 | `nix eval --json .#nixosConfigurations.anis-desktop.config.fonts.packages --apply 'map (p: p.name)'` prints `["geist-serif-1.9.0"]` (Task 1 Step 4). CI `Nix Eval` is green on the PR, which ship checks |
| AC3 | code | Task 1 | Task 1 Step 4's `geist-serif` element eval prints `1.9.0 flat sha256-Hy3Z6pDmjQNYodI0pfFWgHssPg4pXXjYeYCm260fpYw=`: the version, then the fixed-output fetch's hash mode and hash. The Build run, on the Declared verification line, builds it |
| AC4 | evidence | Task 1 | After the owner's `just switch` on mbp after merge: `system_profiler SPFontsDataType \| grep -c "Geist Serif Heart"`. Threshold ≥ 1. Before merge, Task 1 records the base count (0 at planning) as the row's conditions. The acceptance-record row `AC4` is graded `human_pending` (D6) |
| AC5 | evidence | Task 1 | The same switch: `system_profiler SPFontsDataType \| grep -c "FiraCode Nerd Font"`. Threshold ≥ 1. Before merge, Task 1 records the base count (54 at planning). The acceptance-record row `AC5` is graded `human_pending` (D6) |

## Decisions

- Task 1 rests on D1 through D6. Planning appended D6 to the spec: AC4 and AC5 wait on the owner's switch and are graded `human_pending`.
- Planning ran a trial on `a4428457` in a scratch worktree, then discarded it. It used the exact file text in Task 1. The package built four TTFs, 528 KB. When a member name did not match, `unzip` exited 11. The three `fonts.packages` evals printed `["geist-serif-1.9.0"]` on anis-desktop, and `["fira-code-6.2","nerd-fonts-fira-code-3.4.0+6.2","geist-serif-1.9.0"]` on mbp and on eleven-m5. The AC3 eval printed its expected line on mbp and on anis-desktop. Both darwin system closures held `GeistSerif-Heart.ttf` under `fonts/Library/Fonts/Nix Fonts/`. At base, anis-desktop's `fonts.packages` evaluated to `[]`.

---

## Standards review provenance

- Reviewer: Codex (`codex-plan-review`, gpt-6-astra, xhigh), thread `01a18e5a-60e7-7333-b333-3162093e9e96`, fresh isolated read-only mode, no focus.
- Base SHA 07f8981308f56c9ce136773868151a73a2e1da9b; reviewed plan head a4c460c0. No fallback.
- Findings: 0 Blocking, 0 Should fix; Discussion only (AC4/AC5 pending the owner's switch per D6). Accepted 0, rejected 0, deferred 0.
