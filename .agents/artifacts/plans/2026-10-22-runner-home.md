# Studio runner home repair

Fix https://github.com/fagenorn/nix-config/issues/414 per
[spec](../specs/2026-10-22-runner-home-design.md).

## Global Constraints

Preserve the existing account and data; change only this host's declared home.
Inherit signing and include Codex co-author attribution. Use an isolated worktree.
Final verification runs `just build` (timeout 900s) and
`just agent-workflow-tests` (timeout 2400s) once on the final tree.

## Test seams

Actual built activation preflight with the real read-only macOS account lookup;
evaluated mbp home; declared repository verification.

## Delivery estimate and boundaries

Estimated one product file and four added lines; independently deliverable
host configuration repair with no package or dependency changes.

## Task index

Task 1 — Preserve Studio runner home — hosts/darwin/eleven-m5/default.nix — full — [task-1.md](2026-10-22-runner-home.tasks/task-1.md)

## Acceptance map

None — no acceptance criteria.

## Decisions

Per D1 in the spec.

## Plan review

Native Phase-5 reviewer `runner_home_plan_review` at base
`2cbd8fcb73a967d43f4131f14dde6eda0c02c3e1`: clean, no findings.
Native Codex route; no failed external review or fallback.
