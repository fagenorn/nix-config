# Host Capacity Admission Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** `workflow-state control` dispatches an owner only after claiming its
whole owner/worker/reviewer role set against a Nix-declared per-root-session
agent-slot budget, releases claims in the lifecycle write that ends custody,
bounds refused launches, gives every entry path a typed supported/unsupported
answer, and proves it with a deterministic replay baseline
([#150](https://github.com/fagenorn/nix-config/issues/150)).

**Architecture:** A new library `host_admission.py` owns the host declaration
and its vocabulary (Task 1); `workflow-state host-route` is the one typed answer
and the conformance engine reports the declaration (Tasks 1–2). Ledger schema 4
adds the run's `admission` block, released at one commit boundary (Task 3).
Control interface 3 binds a route, adopts, admits per lane and reports capacity
(Task 4), then bounds host refusals (Task 5). A replay over the real CLI records
the baseline (Task 6); the skills, Codex stub and docs land last (Task 7), and
the prep note goes (Task 8).

**Tech stack:** Python 3 stdlib (`unittest`, subprocess round trips; CI runs
Ubuntu 24.04 Python 3.12), JSON, Markdown skill prose, Nix/Home Manager, `just`.

Spec (source of truth, read whole):
`.claude/specs/2026-09-24-issue-150-host-capacity-admission-design.md`, D1–D25.

## Global Constraints

- Out of scope is exactly the spec's `## Out of scope` (no cross-run or
  machine-wide accounting, no per-subagent claims, no Codex adapter or thread
  reads, no lane or release-adapter redesign).
- Admission reasons over declared `agent_slots` only: no CPU, memory,
  Nix-daemon, load or thread-count input anywhere (per D2); `max_parallel`
  keeps its meaning (per D6).
- Role set fixed in the library: controller 1; every owner launch owner 1,
  worker 1, reviewer 1; the supported-route floor is 4 (per D4, D18).
- Route names: grammar `^[a-z][a-z0-9-]{0,63}$`; `direct` is reserved and never
  appears in the declaration (per D3, D18).
- The interface-2 owner, remainder and bootstrap objects, `direct-owner` and
  every owner-side command keep their interfaces (per D3, D8).
- The Arcwave counts are the originating observation only; no metric carries a
  percentage or target field (per D12).
- Tests use temporary roots and `HOME`s only; never open or migrate
  `.superpowers/workflows/` in the primary checkout. The helpers under
  `~/.agents/bin` are `main`'s build: gates run this worktree's scripts.
- A `.nix` change requires `just build` in that task; never `just switch`.
- Every task ends with `just agent-workflow-tests` green (baseline on
  185cc1a: record the count before Task 1); summarize failures to test ids.
- Commits are SSH-signed (never disable signing) and end with the harness's
  attribution trailer lines.

Path abbreviations in members: `S` = `home/common/agent-skills/scripts`,
`T` = `home/common/agent-skills/tests`, `SK` = `home/common/agent-skills/skills`,
`OI` = `home/common/claude-code/skills/orchestrate-issues`.

## Test seams

The spec's S1–S5 only (no private-helper unit tests):
- S1 `workflow-state` subprocess with `HOME` at a fixture declaration:
  `T/test_host_admission.py` (new) and the lifecycle suites through the
  `LifecycleHarness` mixin (per D23).
- S2 the replay: `T/test_admission_replay.py` (new) over `BuilderHarness`, with
  its committed baseline `T/fixtures/admission-replay/baseline.json` (per D12, D23).
- S3 `artifact-budget validate-report --boundary workflow-response` and the
  delivery-model fixture suite (`T/test_delivery_model.py`).
- S4 `T/test_workflow_skill_contracts.py` over source trees, plus its installed
  class under `just agent-installed-skill-tests` (per D25).
- S5 `T/test_conformance.py` / `T/test_conformance_registry.py`.

## Delivery estimate and boundaries

Estimate only: ~17 product files and ~12 test files; the largest deltas are
`S/workflow-state.py` (+~450 lines), tests (+~1,300 lines), `OI/SKILL.md` (±~60).
The diff (est. 150–200 KB) exceeds one review member, so review splits into
three independently testable slices: declaration surface (Tasks 1–2),
lifecycle runtime (Tasks 3–5), evidence and entry paths (Tasks 6–8). Tasks run
in index order; Task 8 is independent.

## Task index

Task 1 — Host declaration, library and `host-route` — `S/host_admission.py` (create), `home/common/agent-skills/host-declaration.json` (create), `S/workflow-state.py`, `S/delivery_model/_wire.py`, `home/common/agent-skills/default.nix`, `justfile`, `T/test_host_admission.py` (create), `T/_delivery_model_fixtures.py`, `T/test_delivery_model.py` — full — [task-1.md](2026-09-24-issue-150-host-capacity-admission.tasks/task-1.md)

Task 2 — Conformance check `host.admission.declaration` — `S/conformance-registry.py`, `S/conformance-checks.py`, `T/test_resolve_project.py`, `T/conformance_test_support.py`, `T/test_conformance.py`, `T/test_conformance_registry.py` — full — [task-2.md](2026-09-24-issue-150-host-capacity-admission.tasks/task-2.md)

Task 3 — Ledger schema 4 and the commit-boundary settle — `S/workflow-state.py`, `S/workflow_delivery.py`, `T/test_workflow_state.py`, `T/test_delivery_workflow.py`, `T/test_host_admission.py` — full — [task-3.md](2026-09-24-issue-150-host-capacity-admission.tasks/task-3.md)

Task 4 — Control interface 3: route binding, admission and the capacity report — `S/workflow-state.py`, `S/workflow_delivery.py`, `S/delivery_model/_wire.py`, `T/test_host_admission.py`, `T/test_workflow_state.py`, `T/test_delivery_workflow.py`, `T/_delivery_model_fixtures.py`, `T/test_delivery_model.py` — full — [task-4.md](2026-09-24-issue-150-host-capacity-admission.tasks/task-4.md)

Task 5 — Bounded launch refusal — `S/workflow-state.py`, `S/workflow_delivery.py`, `S/workflow_delivery_wire.py`, `T/test_host_admission.py`, `T/test_delivery_workflow.py` — full — [task-5.md](2026-09-24-issue-150-host-capacity-admission.tasks/task-5.md)

Task 6 — Deterministic admission replay and baseline — `T/test_admission_replay.py` (create), `T/fixtures/admission-replay/baseline.json` (create), `justfile` — full — [task-6.md](2026-09-24-issue-150-host-capacity-admission.tasks/task-6.md)

Task 7 — Entry paths: Claude adapter, `from-issue` direct route, Codex stub, docs — `OI/SKILL.md`, `OI/evals/evals.json`, `SK/from-issue/SKILL.md`, `home/common/codex/skills/orchestrate-issues/SKILL.md` (create), `home/common/codex/default.nix`, `CLAUDE.md`, `justfile`, `T/test_workflow_skill_contracts.py` — full — [task-7.md](2026-09-24-issue-150-host-capacity-admission.tasks/task-7.md)

Task 8 — Delete the host-admission prep note — `.claude/specs/2026-09-20-host-admission-prep.md` (delete) — mechanical — [task-8.md](2026-09-24-issue-150-host-capacity-admission.tasks/task-8.md)

## Criterion → task trace

| Acceptance criterion (spec table row) | Tasks |
|---|---|
| Claims recorded and released atomically from lifecycle events | 3, 4, 5 |
| Supported route reports available/reserved before launch | 1, 4, 7 |
| Only declared agent slots | 1, 2 |
| Owner-only occupancy cannot over-admit (not a clamp) | 4, 6 |
| Queues excess, no capacity-induced retry loop | 5, 6 |
| Completion releases and wakes the next owner, no polling | 3, 6 |
| Independent review preserved sequentially (floor 4) | 1, 6 |
| Replay metrics and baseline, no percentage target | 6 |
| Claude and Codex entry paths typed | 1, 7 |

## Decisions

The spec's `## Decision ledger` is authoritative. Members cite D1–D17 from
design and the rows planning added: D18 (homes and loading), D19 (release
derivation order), D20 (controller-claim persistence), D21 (slot withholding,
claims per new launch, waiting issues ask for contracts), D22 (`launch_refused`
applicability), D23 (test seams), D24 (conformance check shape) and D25 (Codex
stub home and installed-tree run).

---
