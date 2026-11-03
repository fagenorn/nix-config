# Shared Verification Blocker c4 Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** The callers use the shared verification blocker: `orchestrate-control step` observes every awaited blocker once per step and sends the observations, sdd's Final verification declares a blocker and parks on it, acquire-direct answers a `verification` requirement and relays `suspended`, and the ceilings and docs state what the code does.

**Architecture:** Task 1 adds `observe_all` to `agent_tools.verification_observe` over the path `observe` already uses (D2). Task 2 calls it from `orchestrate-control step`'s `bootstrap`, sends the observations on the first `control` call and reports `verification_refusals`, with the world's local `origin` and its docs (D3, D4, D12). Task 3 writes the owner procedures, raises the breached ceilings and rewrites the lifecycle README's caller protocol, limitations and source-helper rule (D5, D6, D8–D10, D14).

**Tech stack:** Python 3 standard library (`json`, `subprocess`, `unittest`), Git, Just, Nix.

Spec: `.agents/artifacts/specs/2026-11-02-issue-546-verification-blocker-c4-design.md`; a bare "Dn" cites its `## Decision ledger`. Issue: https://github.com/fagenorn/nix-config/issues/546 (boundary c4 of issue 228). c1's rows are "issue 543 Dn", c2's "issue 544 Dn", c3's "issue 545 Dn".

## Global Constraints

- Base `763d8d48570c747ad368d0849939328ad12b49ed`, the immutable delivery base. Spec commits `96de1c5a` and `6c84b89f`, plus the planning commit that appends D16–D17 and the Phase-5 review commit that appends D18.
- Standard library only: `python/pyproject.toml` keeps `dependencies = []`. `orchestrate_control` imports the adapter as a packaged sibling (agent-helpers rule 3).
- Not edited: `workflow-state.py`, `delivery_model/*`, `verification_blocker.py`, the `attempt_*` modules, `lib/agent-tools.nix`, `lifecycle_guard.py`, the allow list's entries, `justfile`, `orchestrate-issues` (both trees), `acquire-durable.md`, `AUTO.md`, `rollover.md`, `delegated-owner.md`, `sdd/SKILL.md`, `CLAUDE.md`, `AGENTS.md`. No ledger schema, interface version or shape moves (D1, D7).
- Comments, docstrings and README sentences describe the code as it behaves at the task's commit, never a later task's. No `TODO` or `FIXME`. Code prose cites `issue 546 Dn`, never a bare `Dn`; commit messages say "issue 546", never a bare `#546`.
- Instruction text grows only in Task 3; `instruction_load check --base <base>` passes at Tasks 1 and 2 (D8). No agent applies the `instruction-budget-raise` label.
- The live lifecycle guard reads a command's raw text, so no gate command or commit message pairs `git` with `push`.
- Run every long command, each test command included, in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>`, with an explicit timeout above its duration. Commit through `launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <git commit args>`; commits are SSH-signed, subjects at most 64 bytes, ending with the session's trailer lines. Scratch files go under the root `launch-scope scratch` prints. Tests use temporary ledgers, repositories and `HOME`s only; no live ledger or retained attempt is read or written. Never run `just switch`, and never push.
- Final gate (sdd runs it once, on the final head): `just build` and `just agent-workflow-tests`, timeout 3600 s each.

## Test seams

- `observe_all` by import in `tests/test_verification_observe.py` (`ObserveAllTest` over `ObserveCase`), the case's environment patched into `os.environ` (D11).
- Gathering through `orchestrate-control step` in `tests/test_orchestrate_control.py` (`GatherTest`), over `OrchestrateWorld` with a local bare `origin`, a publisher and a fetch-logging `git` shim that only those tests install; parking through the source `workflow-state suspend --verification-input -` (D11).
- Skill contracts in `test_workflow_skill_contracts.py`: the two `suspend` templates' argv, the cause order, the lifecycle-call flag, item 5's key set through the source workflow-response validator, the declaration through `normalize_declaration`, both in children (D11, D17); `verification-observe` joins `COMMAND_VOCABULARY` in `test_shell_example_contracts.py`.
- Assertions read exit codes, stdout objects, logged `control` requests, logged `git fetch` argv, refs and replies; never helper call counts. Integration: the focused suites, `just agent-workflow-tests` and `just build`.

## Delivery estimate and boundaries

Figures come from a scratch prototype of all three tasks at the fixed base, green under every task's focused commands and under the AC1 module set while planning, and checked red at each task's Step 2: 525 lines added and 59 deleted over 14 paths. The largest cumulative records at 10 lines of context are `python/README.md` (8/8 lines, 48 KB, long-line context), `instruction-load.json` (9/9 lines, 35 KB), the agent-skills README (7/1 lines, 19 KB), `test_workflow_skill_contracts.py` (91/9 lines, 17 KB) and `orchestrate_control.py` (38/17 lines, 15 KB); the forecasts add about 20 % for fix rounds. One boundary, `all`: c4 is already one child of issue 228, Task 2 needs Task 1's `observe_all`, and Task 3's README states what both landed.

## Task index

Task 1 — Batched observing in the adapter — `python/agent_tools/verification_observe.py`, `tests/test_verification_observe.py`, `python/README.md` — full — [task-1.md](2026-11-02-issue-546-verification-blocker-c4.tasks/task-1.md)

Task 2 — `orchestrate-control step` gathers the awaited observations — `python/agent_tools/orchestrate_control.py`, `tests/orchestrate_world.py`, `tests/test_orchestrate_control.py`, `python/README.md`, `home/common/claude-code/default.nix`, `home/common/agent-skills/README.md` — full — [task-2.md](2026-11-02-issue-546-verification-blocker-c4.tasks/task-2.md)

Task 3 — Owner procedures, ceilings and the lifecycle README — `home/common/agent-skills/skills/sdd/final-review.md`, `home/common/agent-skills/skills/from-issue/SKILL.md`, `home/common/agent-skills/skills/from-issue/acquire-direct.md`, `home/common/agent-skills/instruction-load.json`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `home/common/agent-skills/tests/test_shell_example_contracts.py`, `home/common/agent-skills/README.md`, `python/README.md` — full — [task-3.md](2026-11-02-issue-546-verification-blocker-c4.tasks/task-3.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code (classified) | Task 3 | Step 4's AC1 set: `test_attempt_migration` (migration), `test_verification_suspension` (`HelperGenerationTest`: helper generation and stale-version refusals), `test_control_cutover`, `test_verification_control`, `test_verification_direct`, `test_verification_blocker`, `test_verification_observe` (`ObserveAllTest`, Task 1) and `test_orchestrate_control` (`GatherTest`, Task 2: the source `orchestrate-control` over the source `workflow-state` shim first on `PATH`), plus Task 3's caller pins; the README's source-helper paragraph states the until-activation rule (D10). Red at each task's Step 2. |
| AC2 | code (classified) | Task 3 | Graded in the order the records exist (D18). Final-head clause: the Declared verification line (`just build`, `just agent-workflow-tests`), which Final verification runs at the final head after the acceptance record's commit, so the row's `Observed` is `in final verification` and sdd's `verification_state` and its `Final verification: passed (head <sha>, …)` ledger line report the run. Process clauses, from records that exist before the record's commit: the conformance first pass reads `progress.md` in `sdd-workspace <plan root>` at HEAD and cites, for each of Tasks 1–3, its `Task N: complete` line and the `Delivery gate:` line `sdd-gate next` writes only after that task's projection exits 0; the controller then confirms from the same ledger that the conformance and correctness first-pass verdicts are ledgered separately with distinct reviewer identities before it writes AC2's `Verdict`. Parent and c1–c3 reviews do not count. |
| AC3 | code (classified) | Task 3 | Each task's focused commands; Tasks 2 and 3 Step 4 run `just build`; sdd's final gate runs `just build` and `just agent-workflow-tests`. No command in this plan runs `just switch`; the ship report names source integration (the merge) and host activation (the user's `just switch`) as separate lines. |

## Decisions

The plan rests on the spec's D1–D15. Planning appends D16 (the issue-227 growth pin drops `from-issue/SKILL.md`, whose growth the labelled ceilings gate) and D17 (refines D11: the behavioural skill-contract pins run their source validators in children, because the installed tier has no package on its path). Phase-5 review appends D18 (AC2 graded in the order its records exist; every repair case named in Task 3's step-4 block). After Task 3, the owner declined the raise label (2026-11-03), which appends D19: no ceiling moves, D8 and D16 are reversed, and Task 3's text is trimmed to fit, in one reviewed fix commit.

## Standards review provenance

Reviewer: Codex (`codex-companion` plan-review, gpt-6-astra, xhigh), isolated read-only mode, no focus, base `763d8d48570c747ad368d0849939328ad12b49ed`, plan head `3aed795f`. Accepted 2: B1 (AC2 required `Final verification: passed`, which exists only after the acceptance record's commit: AC2 regraded per D18) and S1 (Task 3's step-4 block named every repair case per D5, D18). Rejected 0, deferred 0. Discussion: the reviewer could not reach api.github.com and used the supplied issue text, which matches the live issue body. No fallback.

---

## Review feasibility delivery

```json
{"actual_evidence":{"head":"d190dd148b6a860ad44074776f8e46fa458eca42","kind":"git-range-ownership/v1","process_ranges":[{"base":"763d8d48570c747ad368d0849939328ad12b49ed","boundaries":["all"],"head":"a4f46fc34ccdc135c64404d28ec538b84729d1b6"},{"base":"28341d621a05338d3cf8ce5c253c296401232418","boundaries":["all"],"head":"c71c1935330b7f1ae6777c7b1502b88c3a849dc3"},{"base":"5263b4dcca73e546a1e99f1cb69a8c9bcb1092dc","boundaries":["all"],"head":"6d0ded4c6282befece037b95652aa51a4d2e33f2"}],"tree":"726d1aff54e2f15c995e25968675b3b388ba2aeb"},"boundaries":[{"acceptance":"Issue 546 complete: AC1-AC3 green under the focused tests, just agent-workflow-tests and just build","depends_on":[],"id":"all","parent":null,"prerequisite":{"kind":"delivery-base"},"process_commit_subject_bytes":[64,64,64,64,64,64,64,64,64,64],"process_forecast_ids":["s","p","t1","t2","t3"],"process_package":{"plan":".agents/artifacts/plans/2026-11-02-issue-546-verification-blocker-c4.md","spec":".agents/artifacts/specs/2026-11-02-issue-546-verification-blocker-c4-design.md","tasks":[".agents/artifacts/plans/2026-11-02-issue-546-verification-blocker-c4.tasks/task-1.md",".agents/artifacts/plans/2026-11-02-issue-546-verification-blocker-c4.tasks/task-2.md",".agents/artifacts/plans/2026-11-02-issue-546-verification-blocker-c4.tasks/task-3.md"]},"tasks":[1,2,3]}],"delivery_base":"763d8d48570c747ad368d0849939328ad12b49ed","derived_from":null,"kind":"review-feasibility-delivery","process_records":[{"bounds":[{"added_lines":520,"boundary":"all","deleted_lines":0,"record_bytes":47104,"support":{"covers":["s"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"s","last_task":3,"owner":0,"path":".agents/artifacts/specs/2026-11-02-issue-546-verification-blocker-c4-design.md"},{"bounds":[{"added_lines":130,"boundary":"all","deleted_lines":0,"record_bytes":18432,"support":{"covers":["p"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p","last_task":3,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-546-verification-blocker-c4.md"},{"bounds":[{"added_lines":180,"boundary":"all","deleted_lines":0,"record_bytes":16384,"support":{"covers":["t1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1","last_task":3,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-546-verification-blocker-c4.tasks/task-1.md"},{"bounds":[{"added_lines":370,"boundary":"all","deleted_lines":0,"record_bytes":30720,"support":{"covers":["t2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t2","last_task":3,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-546-verification-blocker-c4.tasks/task-2.md"},{"bounds":[{"added_lines":280,"boundary":"all","deleted_lines":0,"record_bytes":30720,"support":{"covers":["t3"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t3","last_task":3,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-546-verification-blocker-c4.tasks/task-3.md"}],"proposed_boundary":"all","schema_version":3}
```
