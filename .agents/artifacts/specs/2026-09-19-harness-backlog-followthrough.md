# Harness backlog follow-through — 2026-09-19

This ledger records the approved tracker changes derived from the [backlog audit](2026-09-19-harness-backlog-audit.md) and [retrospective](2026-09-19-agent-harness-retrospective.md). It contains issue contracts and relationships, not private transcript material.

## Updated backlog

- [#37](https://github.com/fagenorn/nix-config/issues/37): advisory-first workflow-test CI rollout.
- [#39](https://github.com/fagenorn/nix-config/issues/39): three unfinished CI minors; the landed checkout upgrade was removed.
- [#97](https://github.com/fagenorn/nix-config/issues/97): delivered telemetry pending schema mapping and accounting acceptance.
- [#98](https://github.com/fagenorn/nix-config/issues/98): versioned observed-versus-declared runtime/model drift.
- [#99](https://github.com/fagenorn/nix-config/issues/99): coordination parent for review-sized behavior and prose fixes; 417 means 119 + 64 + 37 + 197 recurring errors.
- [#100](https://github.com/fagenorn/nix-config/issues/100): canonical resolver migration and legacy fallback retirement.
- [#116](https://github.com/fagenorn/nix-config/issues/116), [#117](https://github.com/fagenorn/nix-config/issues/117), and [#130](https://github.com/fagenorn/nix-config/issues/130): human-required gates retained and refreshed against current behavior.
- [#121](https://github.com/fagenorn/nix-config/issues/121): recovery coordination parent; retained branch and worktree remain read-only evidence.
- [#123](https://github.com/fagenorn/nix-config/issues/123)–[#129](https://github.com/fagenorn/nix-config/issues/129): staged acceptance and dependencies refreshed without changing settled decisions.
- [#38](https://github.com/fagenorn/nix-config/issues/38): unchanged and ready.

## Created slices

- [#147](https://github.com/fagenorn/nix-config/issues/147): recover #121 Tasks 1–3, platform manifest and status.
- [#148](https://github.com/fagenorn/nix-config/issues/148): recover #121 Tasks 4–6, adoption plan/apply/verify; blocked by #147.
- [#149](https://github.com/fagenorn/nix-config/issues/149): complete #121 Tasks 7–8, real adoption and registration; blocked by #148.
- [#150](https://github.com/fagenorn/nix-config/issues/150): runtime agent-slot admission and host capability, excluding general host-resource scheduling.
- [#151](https://github.com/fagenorn/nix-config/issues/151): completed-deliverable reconciliation and authorization propagation.
- [#152](https://github.com/fagenorn/nix-config/issues/152): early review-package feasibility and shared infrastructure blockers.
- [#153](https://github.com/fagenorn/nix-config/issues/153): leaf-agent, read-before-write, and optional-config behavior contracts.
- [#154](https://github.com/fagenorn/nix-config/issues/154): shell examples aligned with the worktree checker.
- [#155](https://github.com/fagenorn/nix-config/issues/155): context consolidation; blocked by #153 and #154.

Native GitHub dependency edges mirror the superseding blocker sections. Closed historical blockers were removed where the updated contract replaces them. No issue was closed and no acceptance checkbox was marked.

## Delivered implementation — PR #156

The reviewed head `22c39b837040916cfba3d920c9bb295648ea5e87` merged through PR #156 as `6d4b7a49dd3a44c079c8310e902a86665a6805f0`. Local main was fast-forwarded and this task’s clean branch/worktree were removed. It corrects Codex accounting and adds the bounded workflow safeguards for scoped authorization, delivered-work reconciliation, and cumulative review-package checks. Runtime reservations, terminal postcondition schemas, forecast machinery and shared blocker identity remain in #150–152.

Verification: 756 workflow tests passed, Nix build passed without activation, both independent whole-branch review axes are clean after one consolidated fix wave, and six independent plan-only workflow probes exercised intended boundaries. The final cumulative package was 167,068 bytes with full changed-file coverage. The two retained audit samples still produce 185,069,427 and 261,290,381 input-plus-output tokens.

The user explicitly authorized full delivery after automatic approval review requested destination-specific permission. The reviewed branch is now published as [PR #156](https://github.com/fagenorn/nix-config/pull/156), with exact head `22c39b837040916cfba3d920c9bb295648ea5e87`. Required Nix Eval and Flake Checker passed; PR #156 is merged and #97 is closed with all acceptance checkboxes verified. #98 and #150–152 retain explicit remaining work. No activation has been performed; installed skills update on the next configuration activation.

Original #121 and #127 worktrees retain heads `fe85677c8bd26c808ac69c2ee21b17ff6e262923` and `dd233c8e94970d48066c200550e7c558e2ce695a` respectively.
