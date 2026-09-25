# Ungated agent merges

**Idea:** pre-authorize `gh pr merge` for background agents with no required PR check — let ship-issue's internal gates (build, two-axis review, degradation gate) be the only protection.

**Rejected:** 2026-08-17, while breaking the orchestration-run findings into issues. Merge safety must come from a required status check on the PR, not from the permission classifier or skill-internal gates alone. The permission rule ships only behind the CI gate.

**Links:** https://github.com/fagenorn/nix-config/issues/29 (the gate), https://github.com/fagenorn/nix-config/issues/30 (the permission surface, blocked by the gate).
