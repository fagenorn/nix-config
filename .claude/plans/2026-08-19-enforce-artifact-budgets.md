# Artifact Budget Enforcement Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Enforce one repository-owned byte-budget policy so design specs, implementation plans, handoffs, and review packages can report success only after a valid final measurement.

**Architecture:** A strict standard-library Python module owns policy loading, package discovery, byte accounting, violation classification, and the `artifact-budget check` CLI. Plan and review artifacts use convention-named packages behind one root; their producer skills/scripts apply deterministic remediation, and workflow consumers validate the root plus four metrics before advancing.

**Tech stack:** Python 3 standard library, Bash adapters, JSON/Markdown skill contracts, `unittest`, Home Manager/Nix, Just.

## Global Constraints

- The authoritative design is `.claude/specs/2026-08-19-artifact-budget-policy-design.md`; implementations cite D1–D16 and do not duplicate decision rationale.
- Exact limits are: design spec 65,536 bytes; implementation-plan root 16,384 bytes, member 49,152 bytes, eight members, aggregate 131,072 bytes; handoff 8,192 bytes; review-package root 16,384 bytes, member 65,536 bytes, eight members, aggregate 524,288 bytes.
- Both `diff-review` and durable `delivery-detail` manifest variants are `review-package`; they use that one policy entry and introduce no unbudgeted report artifact or copied numeric ceiling.
- All sizes are encoded bytes, not characters or model tokens; booleans are not integers in policy, result, metric, or manifest fields. Git binary numstat `-` contributes zero insertions/deletions while the file and binary patch remain covered.
- `artifact-budget check --kind <design-spec|implementation-plan|handoff|review-package> --root <path> [--policy <path>] --format json` exits 0 only for `within_budget`, 3 only for valid `over_budget`, and 2 for invalid input. `artifact-budget validate-report --boundary <producer|sdd|ship-handoff|ship-summary> --input <path|-> [--policy <path>]` canonicalizes one strict UTF-8 JSON object on exit 0 and emits no stdout on exit 2.
- `artifact-budget validate-detail-input --input <path|-> [--policy <path>]` is the sole strict non-empty finding-input validator used by generation and every unpublished-detail consumer.
- A producer report has exactly `state`, one root `artifact`, and `notes`; it carries no `decisions`, `open_items`, `adr_paths`, member lists, or summary field. Successful artifact metrics are exactly `root_bytes`, `total_bytes`, `file_count`, and `largest_member_bytes`; the notes limit comes only from the shared policy.
- Every phase boundary uses the exhaustive state/nullability matrix in D14: producers write candidate JSON and transport only validated stdout; callers validate received bytes again. No Markdown/YAML report is authoritative.
- The one shared policy bounds notes at 500 characters and every report wire object at 8,192 encoded bytes; skills contain neither number.
- Measurement happens after the final mutation. Any later writer owns remeasurement; no missing or stale measurement permits a successful state.
- Plans keep shared constraints in this root and task-specific contracts in convention-named members; reviewers and implementers receive paths plus compact metrics, never artifact contents or member lists.
- SDD and ship review persist non-empty detail as a `delivery-detail` review-package below the primary checkout's `.superpowers/issue-delivery/` home before removable-worktree cleanup; callers receive one main-root-relative `report_path`, never a findings list.
- If that publication fails, closed `detail_state: unpublished` carries only the readable retained-candidate path and bounded notes; SDD/ship fail or stop and must not remove its workspace/worktree.
- The only over-budget transitions are those in the spec: design/grill compact then `decompose_required`; planning compact/split then `decompose_required`; handoff rewrite once then `stopped`; review-package generation then `decompose_required`.
- Historical artifacts are not migrated. Model/token budgets, attempt budgets, general product diff-size gates, and CI wiring remain out of scope, except for the D9/D10 compatibility required by the new package roots.
- Use the Python standard library only, preserve existing public workflow semantics not explicitly changed here, append `Co-Authored-By: Codex <noreply@openai.com>`, and never disable commit signing.

## Test seams

- `artifact-budget check` and `validate-report` are the primary seams: table-driven CLI tests use repository-owned artifact descriptors and every valid/invalid boundary matrix row through stdin and file input for deterministic JSON and fail-closed errors.
- `sdd/scripts/task-brief` is the plan-consumer seam: it validates a package root and resolves exactly one indexed task member without reading other task bodies.
- `sdd/scripts/review-package` is the review-producer seam: temporary Git ranges and detail inputs prove both strict variants, deterministic commits/bytes, durable lifetime, mutation-point no-clobber races, complete manifests, metrics, and truthful oversize stops.
- `just agent-workflow-tests` pins producer/caller ordering, final-writer remeasurement, fixed reports, small/oversized transitions, and root-only dispatches.
- `just build` is the publication seam for the installed module, command, policy, and updated skills.

## Task index

Task 1 — Build the authoritative budget checker and publish its policy — `home/common/agent-skills/artifact-budget-policy.json`, `home/common/agent-skills/scripts/{artifact-budget,artifact_budget.py}`, `home/common/agent-skills/tests/fixtures/artifact-budgets/{small-issue,oversized-issue}.json`, `home/common/agent-skills/tests/test_artifact_budget.py`, `home/common/agent-skills/default.nix`, `Justfile` — full — [task-1.md](2026-08-19-enforce-artifact-budgets.tasks/task-1.md)

Task 2 — Produce and consume indexed implementation-plan packages — `home/common/agent-skills/skills/writing-plans/SKILL.md`, `home/common/agent-skills/skills/sdd/{SKILL.md,scripts/task-brief}`, `home/common/agent-skills/skills/from-issue/REVIEW-CONTRACT.md`, `home/common/claude-code/skills/codex-collaboration/PLAN-REVIEW.md`, `home/common/agent-skills/tests/{test_task_brief.py,test_workflow_skill_contracts.py}`, `Justfile` — full — [task-2.md](2026-08-19-enforce-artifact-budgets.tasks/task-2.md)

Task 3 — Generate bounded review manifests and whole-file diff shards — `home/common/agent-skills/skills/sdd/{SKILL.md,fix-loop.md,final-review.md,task-reviewer-prompt.md,re-review-prompt.md,conformance-reviewer-prompt.md,correctness-reviewer-prompt.md,scripts/review-package}`, `home/common/claude-code/skills/codex-collaboration/{DIFF-REVIEW.md,evals/evals.json}`, `home/common/agent-skills/tests/{test_review_package.py,test_workflow_skill_contracts.py}`, `Justfile` — full — [task-3.md](2026-08-19-enforce-artifact-budgets.tasks/task-3.md)

Task 4 — Enforce budgets in single-file artifact producers — `home/common/agent-skills/skills/{design/SKILL.md,grill-with-docs/SKILL.md,handoff/SKILL.md}`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — [task-4.md](2026-08-19-enforce-artifact-budgets.tasks/task-4.md)

Task 5 — Close the orchestration contract and run repository gates — `home/common/agent-skills/skills/from-issue/{SKILL.md,AUTO.md,standards-review.md,ship-handoff.md}`, `home/common/agent-skills/skills/ship-issue/{SKILL.md,REVIEW.md}`, `home/common/agent-skills/skills/sdd/SKILL.md`, `home/common/agent-skills/scripts/workflow-state.py`, `home/common/agent-skills/tests/{test_workflow_skill_contracts.py,test_workflow_state.py}` — full — [task-5.md](2026-08-19-enforce-artifact-budgets.tasks/task-5.md)

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
- D14 defines the canonical report CLI and exhaustive boundary matrices used by all tasks.
- D15 defines the budgeted durable delivery-detail package and cleanup lifetime used by Tasks 3 and 5.
- D16 replaces D12's racy rename step with mutation-point no-clobber publication in Task 3.

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

### Second review

- Reviewer: `/root/issue49_plan_rereview` (native reviewer; no fallback).
- Review artifact: `/tmp/issue49-plan-rereview.md`; reviewed head `53ad1d8fda183e40808de0473f4625c7f0cb1933`; base `416e7a92795a282c1b8cdd71e35a0f570cd35e56`; isolated/read-only.
- Accepted 4 Blocking and 1 Should-fix findings; rejected 0; deferred 0.
- R-B1/R-B2: added canonical JSON CLI validation and exhaustive valid/invalid boundary rows (D14).
- R-B3: added a primary-checkout durable detail package, cleanup order, and path-lifetime seam (D15).
- R-B4: replaced check/rename with exclusive identity-tracked publication and race injections (D16).
- R-S1: applied fixture dates to every commit and added byte-repeatability coverage.

### Final review

- Reviewer: `/root/issue49_plan_final_review` (native reviewer; no fallback).
- Review artifact: `/tmp/issue49-plan-final-review.md`; reviewed head `f7500284e163545105c6718eca586fe921613590`; base `416e7a92795a282c1b8cdd71e35a0f570cd35e56`; isolated/read-only.
- Accepted 3 Blocking and 1 Should-fix findings; rejected 0; deferred 0.
- F-B1: split failed-after-range SDD validation into empty-detail/null-path and non-empty-detail/durable-path rows, including the pre-dispatch package-failure case (D14).
- F-B2: made the detail producer derive and police its primary-checkout destination, identity, and linked-worktree trust boundary (D15).
- F-B3: corrected the parked-detail fixture and added fail-closed null-ruling coverage.
- F-S1: made the delivery home establish its own exact no-follow ignore boundary and verify it with `git check-ignore` (D15).

### Clean check

- Reviewer: `/root/issue49_plan_clean_check` (native reviewer; no fallback).
- Review artifact: `/tmp/issue49-plan-clean-check.md`; reviewed head `374f903129c852bfaec6859272e0860970c197c5`; base `416e7a92795a282c1b8cdd71e35a0f570cd35e56`; isolated/read-only.
- Accepted 1 Blocking and 1 Should-fix finding; rejected 0; deferred 0.
- C-B1: added failure-only unpublished-detail transport with retained-candidate readability and cleanup prohibition (D14/D15).
- C-S1: completed CLI rejection coverage for issue, producer, and head identity fields.

### Closure check

- Reviewer: `/root/issue49_plan_closure` (native reviewer; no fallback).
- Review artifact: `/tmp/issue49-plan-closure.md`; reviewed head `6ed00cb74ca1f1d34f57c0dcec8bcf61e38d1d3a`; base `416e7a92795a282c1b8cdd71e35a0f570cd35e56`; isolated/read-only.
- Accepted 2 Blocking findings; rejected 0; deferred 0.
- CL-B1: added one shared strict detail-input CLI and required canonical validation before unpublished persistence (D14/D15).
- CL-B2: merged default and per-case identity kwargs so malformed-head cases reach the CLI.

### Final closure

- Reviewer: `/root/issue49_plan_final_closure` (native reviewer; no fallback).
- Review artifact: `/tmp/issue49-plan-final-closure.md`; reviewed head `f4756fff64116a428e05a6363e82b22ff86ba8ea`; base `416e7a92795a282c1b8cdd71e35a0f570cd35e56`; isolated/read-only.
- Accepted 1 Should-fix finding; rejected 0; deferred 0; no Blocking findings remained.
- FC-S1: made every detail destination/identity negative test start from a valid non-empty finding payload, so the intended path or identity field is the only invalid condition.

Task members are the normative executable instructions. Read this root once for shared constraints and then only the selected linked member.
