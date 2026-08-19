# Artifact Budget Enforcement Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Enforce one repository-owned byte-budget policy so design specs, implementation plans, handoffs, and review packages can report success only after a valid final measurement.

**Architecture:** A strict standard-library Python module owns policy loading, package discovery, byte accounting, violation classification, and the `artifact-budget check` CLI. Plan and review artifacts use convention-named packages behind one root; their producer skills/scripts apply deterministic remediation, and workflow consumers validate the root plus four metrics before advancing.

**Tech stack:** Python 3 standard library, Bash adapters, JSON/Markdown skill contracts, `unittest`, Home Manager/Nix, Just.

## Global Constraints

- The authoritative design is `.claude/specs/2026-08-19-artifact-budget-policy-design.md`; implementations cite D1–D13 and do not duplicate decision rationale.
- Exact limits are: design spec 65,536 bytes; implementation-plan root 16,384 bytes, member 49,152 bytes, eight members, aggregate 131,072 bytes; handoff 8,192 bytes; review-package root 16,384 bytes, member 65,536 bytes, eight members, aggregate 524,288 bytes.
- All sizes are encoded bytes, not characters or model tokens; booleans are not integers in policy, result, metric, or manifest fields. Git binary numstat `-` contributes zero insertions/deletions while the file and binary patch remain covered.
- `artifact-budget check --kind <design-spec|implementation-plan|handoff|review-package> --root <path> [--policy <path>] --format json` exits 0 only for `within_budget`, 3 only for a valid `over_budget` measurement, and 2 for every invocation, policy, package-shape, schema, or I/O failure.
- A producer report has exactly `state`, one root `artifact`, and `notes`; it carries no `decisions`, `open_items`, `adr_paths`, member lists, or summary field. Successful artifact metrics are exactly `root_bytes`, `total_bytes`, `file_count`, and `largest_member_bytes`; the notes limit comes only from the shared policy.
- Measurement happens after the final mutation. Any later writer owns remeasurement; no missing or stale measurement permits a successful state.
- Plans keep shared constraints in this root and task-specific contracts in convention-named members; reviewers and implementers receive paths plus compact metrics, never artifact contents or member lists.
- The only over-budget transitions are those in the spec: design/grill compact then `decompose_required`; planning compact/split then `decompose_required`; handoff rewrite once then `stopped`; review-package generation then `decompose_required`.
- Historical artifacts are not migrated. Model/token budgets, attempt budgets, general product diff-size gates, and CI wiring remain out of scope, except for the D9/D10 compatibility required by the new package roots.
- Use the Python standard library only, preserve existing public workflow semantics not explicitly changed here, append `Co-Authored-By: Codex <noreply@openai.com>`, and never disable commit signing.

## Test seams

- `artifact-budget check` is the primary seam: table-driven CLI tests use repository-owned small/oversized descriptors and temporary payloads for boundaries, strict schemas, discovery, deterministic JSON, and fail-closed errors.
- `sdd/scripts/task-brief` is the plan-consumer seam: it validates a package root and resolves exactly one indexed task member without reading other task bodies.
- `sdd/scripts/review-package` is the review-producer seam: temporary Git ranges prove complete ordered sharding, complete manifests, metrics, and truthful oversize stops.
- `just agent-workflow-tests` pins producer/caller ordering, final-writer remeasurement, fixed reports, small/oversized transitions, and root-only dispatches.
- `just build` is the publication seam for the installed module, command, policy, and updated skills.

## Task index

Task 1 — Build the authoritative budget checker and publish its policy — `home/common/agent-skills/artifact-budget-policy.json`, `home/common/agent-skills/scripts/{artifact-budget,artifact_budget.py}`, `home/common/agent-skills/tests/fixtures/artifact-budgets/{small-issue,oversized-issue}.json`, `home/common/agent-skills/tests/test_artifact_budget.py`, `home/common/agent-skills/default.nix`, `Justfile` — full — [task-1.md](2026-08-19-enforce-artifact-budgets.tasks/task-1.md)

Task 2 — Produce and consume indexed implementation-plan packages — `home/common/agent-skills/skills/writing-plans/SKILL.md`, `home/common/agent-skills/skills/sdd/{SKILL.md,scripts/task-brief}`, `home/common/agent-skills/skills/from-issue/REVIEW-CONTRACT.md`, `home/common/claude-code/skills/codex-collaboration/PLAN-REVIEW.md`, `home/common/agent-skills/tests/{test_task_brief.py,test_workflow_skill_contracts.py}`, `Justfile` — full — [task-2.md](2026-08-19-enforce-artifact-budgets.tasks/task-2.md)

Task 3 — Generate bounded review manifests and whole-file diff shards — `home/common/agent-skills/skills/sdd/{SKILL.md,fix-loop.md,final-review.md,task-reviewer-prompt.md,re-review-prompt.md,conformance-reviewer-prompt.md,correctness-reviewer-prompt.md,scripts/review-package}`, `home/common/claude-code/skills/codex-collaboration/{DIFF-REVIEW.md,evals/evals.json}`, `home/common/agent-skills/tests/{test_review_package.py,test_workflow_skill_contracts.py}`, `Justfile` — full — [task-3.md](2026-08-19-enforce-artifact-budgets.tasks/task-3.md)

Task 4 — Enforce budgets in single-file artifact producers — `home/common/agent-skills/skills/{design/SKILL.md,grill-with-docs/SKILL.md,handoff/SKILL.md}`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-4.md](2026-08-19-enforce-artifact-budgets.tasks/task-4.md)

Task 5 — Close the orchestration contract and run repository gates — `home/common/agent-skills/skills/from-issue/{SKILL.md,AUTO.md,standards-review.md,ship-handoff.md}`, `home/common/agent-skills/skills/ship-issue/SKILL.md`, `home/common/agent-skills/skills/sdd/SKILL.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-5.md](2026-08-19-enforce-artifact-budgets.tasks/task-5.md)

## Decisions

- D1/D2 define the checker authority, strict byte arithmetic, and exact ceilings used by Task 1.
- D3/D8 define the indexed-plan root/member wire format used by Task 2.
- D4/D8/D9 define review manifest fields, whole-file sharding, and the scoped-correctness exception used by Task 3.
- D5/D6 define final-writer measurement, truthful stops, and compact report contracts used by Tasks 2–5.
- D7 defines the CLI, workflow-fixture, and build seams used across all tasks.
- D10 defines the ship-time plan-member expansion in Task 5 without changing public root-only handoffs.
- D11 defines the exact bounded report and ship-summary transport used by Tasks 1, 2, 4, and 5.
- D12 defines deterministic staged review-package publication/refusal used by Task 3.
- D13 defines behavioral descriptors and strict manifest/binary accounting used by Tasks 1 and 3.

## Standards review provenance

- Reviewer: `/root/issue49_plan_review` (native reviewer; no fallback).
- Review artifact: `/tmp/issue49-plan-review.md`; reviewed head `1240cb7e8398d860210419c98fe4667e63091cd7`; base `416e7a92795a282c1b8cdd71e35a0f570cd35e56`; isolated/read-only.
- Accepted 2 Blocking and 4 Should-fix findings; rejected 0; deferred 0.
- B1: removed unbounded producer/ship list and summary transport; added exact policy-validated reports and negative legacy/over-limit cases (D11).
- B2: added `fix-loop.md` to Task 3 and pinned exit-2/exit-3 no-dispatch behavior.
- S1: made every descriptor case materialize bytes and run through the checker CLI (D13).
- S2: selected staged first-publication plus untouched refusal for existing packages (D12).
- S3: rejected manifest booleans and matched binary zero-churn stat precedent (D13).
- S4: added a real executable wrapper and source test runtime matching Home Manager publication.

Task members are the normative executable instructions. Read this root once for shared constraints and then only the selected linked member.
