# Attempt Run Identity on the Transaction Core Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** every attempt run gets exactly one identity, a core `rel_` UUIDv7 run transaction, and every legacy ledger in one of the four legacy dialects migrates to schema 8 by a dry-run-first, adjacent, atomic, idempotent step that keeps its legacy handle working for live owners.

**Architecture:** a pure module `agent_tools.attempt_identity` holds the dialect grammar, creation keys, the `attempt-run/v1` subject, the 7 → 8 plan and the migration report, and the core gains a read-only `TransactionStore.lookup`. A second package module, `agent_tools.attempt_store`, holds the store effects: store root, mint lock, minting, lookup, binding and `migrate`'s rows and report (D27). `workflow-state` keeps each ledger's `state.lock`, the ledger read and commit, the delivery chain and `validate_state`, and is a thin caller for `init-run --creation-key`, `direct-owner` and `migrate`. Installed `workflow-state` runs under the agent_tools interpreter so it can import the core, and `launch-scope` accepts a `rel_` handle (D18).

**Tech stack:** Python 3 standard library and `unittest`; `agent_tools` (`transaction_core`, `transaction_storage`); Nix (`lib/agent-tools.nix`, home-manager); `just`.

Spec: `.agents/artifacts/specs/2026-10-09-issue-337-attempt-identity-migration-design.md`. Its `## Decision ledger` rows D1–D36 are cited by ID.

## Global Constraints

- Delivery base and budget baseline: `907dba234933e1457c2883530bf5f1b83e07a0ec`, the merge base with `origin/main` (D33). The old-helper test still pins `eca16cd85453dd290a9ab8ac66b8b3f2f7e697d7` (D13, D34).
- **Never touch a live ledger.** `/Users/anis/tmp/nix-config/.superpowers/` holds the ledgers of the orchestration that runs this plan. No test, command or manual check may run `workflow-state migrate --apply`, a lifecycle write, or any built `workflow-state` against it, or against any `--repo-root` other than a `tempfile` directory. Every test builds its ledgers under `tempfile.TemporaryDirectory()`.
- Subject, creation-key and report literals are the constants `agent_tools.attempt_identity` defines (Task 1); no later task restates or changes them.
- Closed refusal reasons: `unknown_schema`, `invalid_state`, `unknown_dialect`, `ambiguous_lineage`, `location_mismatch`. Verdicts: `current`, `migrate`, `migrated`, `refused`.
- Store root `<repo root>/.superpowers/attempt-transactions/`, holding a `*` `.gitignore`. Mint lock `<store root>/attempt-runs.lock`, a blocking exclusive `flock` that wraps every `create`. Lock order, outermost first: `.direct-<issue>.lock` → ledger `state.lock`s → mint lock → core locks. No `state.lock` is taken while the mint lock is held (D9).
- New helper code follows `docs/standards/agent-helpers.md`: no `sys.path` edits, and no new path loading; `workflow-state` output keeps its existing `print_json` rendering (sorted keys, compact). `workflow-state.py` imports `agent_tools.attempt_identity` and `agent_tools.attempt_store` with a plain `import` (D11, D27).
- Prose that a task writes into code or docs must describe the code as it is at that task's head. Where a task gives content points rather than text, the implementer writes the sentences from the implemented code.
- Every long command, each test command included, runs in the foreground as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>` from the worktree root, with an explicit timeout above its duration. Commits go through `launch-commit … -- <git commit args>`, signed, with the session's trailers. Scratch files live under `launch-scope scratch`'s root.
- Python tests run as `PYTHONPATH="$PWD/python" python3 -m unittest <file> [-k <pattern>]`, with a timeout of at least 900 s.
- Tasks 1–5 are complete (`1701032a`, `aae76ba8`, `b5519a4b`, `1d4552b6`, `6ae38b0c`), carried onto the delivery base by merge `cd7c09f7` (D32), and are not re-run; execution resumes at Task 6. The lifecycle suites, red from Task 2 until Task 5's sweep, are green at `cd7c09f7` (2507 tests OK), and every later task keeps them green.
- Review-package budget (D29, D33): `git diff -U10 907dba234933e1457c2883530bf5f1b83e07a0ec..HEAD -- <file> | wc -c` stays at most 60000 for every changed code or test file after every task, and the cumulative `review-package` check from the delivery base at each task head reports `complete`.
- No task raises an instruction ceiling or edits `instruction-load.json` (D22).
- Final gate, run once on the final head by Task 8: `just build` (timeout 3600 s), `just agent-workflow-tests` (timeout 3600 s) and `just agent-installed-skill-tests` (timeout 3600 s). Task 8 also runs `just agent-instruction-budget` with no `--raise-label`. No agent applies the `instruction-budget-raise` label.

## Test seams

- The workflow-state CLI driven from source through `LifecycleHarness.run_cli`. Its stdout, ledger bytes and `.superpowers` tree are the observable behaviour. The migration fixtures live in the new `home/common/agent-skills/tests/test_attempt_migration.py`.
- `agent_tools.attempt_identity`'s pure functions and `TransactionStore.lookup`, imported normally by the new `tests/test_attempt_identity.py`. `agent_tools.attempt_store` is tested only through the CLI seam above (D27).
- The installed layout: `tests/test_agent_tools_launchers.py` over the built home-manager files (Task 8 only).
- A "tree snapshot" is `{relative path: bytes or "<dir>"}` for every path under `<root>/.superpowers`.

## Delivery estimate and boundaries

Measured at `cd7c09f7` (Tasks 1–5 done), `git diff -U10 907dba23...cd7c09f7` per file, in bytes: `workflow-state.py` 54166; `test_workflow_state.py` 45246; `test_delivery_workflow.py` 44148; `test_attempt_migration.py` 13820; `attempt_identity.py` 13613; `attempt_store.py` 13537; `tests/test_attempt_identity.py` 10620; `test_admission_replay.py` 5869; `test_delivered_control.py` 3967; `test_host_admission.py` 3430; `transaction_core.py` 3278; `tests/test_launch_scope.py` 2550; `workflow_delivery.py` 2360; `tests/test_transaction_core.py` 2204; `justfile` 2129. That is 15 code and test files, about 221 KB.

`review-package` packs whole per-file `-U10` records, plan and spec files included, into at most 8 members of at most 65536 bytes and 524288 in all, so 15+ files fit while no record exceeds 65536. At the amendment's parent it reports `complete`: 7 members, largest 64674, total 398606; condensing the completed members (D35) frees more.

Remaining growth (estimates): Task 6 adds about 3800 bytes to `workflow-state.py` (to about 58000, under the 60000 ceiling), about 7000 to `attempt_store.py` and about 18000 to `test_attempt_migration.py`; Task 7 brings `test_attempt_migration.py` to about 45000; Task 8 adds 8 small records, about 47000 bytes in all. The forecast below carries these bounds per path for `review-feasibility project` (D36). Fallback slices: Tasks 1–5 and Tasks 6–8. At `50046121`, `--completed-through 5` projects `complete`: 8 members, largest 65503, total 451217.

## Task index

Task 1 — Core `lookup` and the pure `attempt_identity` module (complete, `1701032a`) — files as listed in the member — full — [task-1.md](2026-10-09-issue-337-attempt-identity-migration.tasks/task-1.md)
Task 2 — Ledger schema 8 and `init-run` minting (complete, `aae76ba8`) — files as listed in the member — full — [task-2.md](2026-10-09-issue-337-attempt-identity-migration.tasks/task-2.md)
Task 3 — `direct-owner` on run transactions (complete, `b5519a4b`) — files as listed in the member — full — [task-3.md](2026-10-09-issue-337-attempt-identity-migration.tasks/task-3.md)
Task 4 — Move the attempt store into `agent_tools.attempt_store` (complete, `1d4552b6`) — files as listed in the member — full — [task-4.md](2026-10-09-issue-337-attempt-identity-migration.tasks/task-4.md)
Task 5 — Regression floor: the existing suites on minted and legacy-dialect runs (complete, `6ae38b0c`) — files as listed in the member — full — [task-5.md](2026-10-09-issue-337-attempt-identity-migration.tasks/task-5.md)
Task 6 — `workflow-state migrate`: dry run, apply and report, with the logic in `attempt_store` — `python/agent_tools/attempt_store.py`, `home/common/agent-skills/scripts/workflow-state.py`, `home/common/agent-skills/tests/test_attempt_migration.py` — full — [task-6.md](2026-10-09-issue-337-attempt-identity-migration.tasks/task-6.md)
Task 7 — Live legacy owner and old-helper refusal — `home/common/agent-skills/tests/test_attempt_migration.py` — full — [task-7.md](2026-10-09-issue-337-attempt-identity-migration.tasks/task-7.md)
Task 8 — Installed `workflow-state`, skill text, READMEs and the final gate — `lib/agent-tools.nix`, `home/common/agent-skills/default.nix`, `tests/test_agent_tools_launchers.py`, `home/common/claude-code/skills/orchestrate-issues/SKILL.md`, `home/common/agent-skills/skills/from-issue/acquire-durable.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `python/README.md`, `home/common/agent-skills/README.md` — full — [task-8.md](2026-10-09-issue-337-attempt-identity-migration.tasks/task-8.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 6 | `test_attempt_migration.py`: `MigrationAcceptanceTest.test_ac1_minted_runs_and_legacy_rows_with_lineage`, run by `just agent-workflow-tests` |
| AC2 | code | Task 6 | `test_attempt_migration.py`: `MigrationAcceptanceTest.test_ac2_identity_never_comes_from_names` |
| AC3 | code | Task 6 | `test_attempt_migration.py`: `MigrationAcceptanceTest.test_ac3_dry_run_then_idempotent_apply`, `test_ac3_refusals_are_byte_identical`, `test_ac3_precreated_transaction_is_bound`, `test_ac3_held_mint_lock_makes_apply_wait` |
| AC4 | code | Task 7 | `test_attempt_migration.py`: `LegacyOwnerCompatibilityTest.test_control_migrates_under_a_live_owner`, `test_owner_write_is_the_migrating_write`, `test_base_helper_refuses_schema_8_without_writing` |
| AC5 | code | Task 8 | `just agent-workflow-tests` green at the final head with Task 5's sweep as the only change to pre-existing tests, `test_admission_replay` on its committed baseline; `just build` |

## Decisions

- Identity, subject, alias index, lookup, lineage and legacy handle: D1–D6. Package module, exit codes, mint lock, no reverse transform, interpreter: D7–D11, D16.
- `init-run --run-id`, old-helper pin, bind on locked reads: D12–D14. Direct reservation, direct-owner minting, `rel_` handles, sweep, `RunIdentity` threading, fixtures, ceilings: D15, D17–D22.
- Plan-review dispositions: D23–D26. Review-package amendment (store module, store location, `-U10` ceilings, task renumbering, sweep adaptation): D27–D31.
- Resume: carry-forward by merge D32, budget baseline `907dba23` D33, old-helper pin D34, condensed completed members D35, forecast ownership D36.

## Review feasibility delivery

```json
{"actual_evidence":{"head":"cd7c09f7e8f8c48f9430d5c909a0a7e356d0ab45","kind":"git-range-ownership/v1","process_ranges":[],"tree":"569bc29cfd61bb8e16d01abb6550effb7c651dc0"},"boundaries":[{"acceptance":"#337 AC1-AC5 green under just agent-workflow-tests and just build.","depends_on":[],"id":"attempt-identity","parent":null,"prerequisite":{"kind":"delivery-base"},"process_commit_subject_bytes":[72,72,72,72],"process_forecast_ids":["p1","p2","p3","p4","p5","p6","p7","p8","p9","p10"],"process_package":{"plan":".agents/artifacts/plans/2026-10-09-issue-337-attempt-identity-migration.md","spec":".agents/artifacts/specs/2026-10-09-issue-337-attempt-identity-migration-design.md","tasks":[".agents/artifacts/plans/2026-10-09-issue-337-attempt-identity-migration.tasks/task-1.md",".agents/artifacts/plans/2026-10-09-issue-337-attempt-identity-migration.tasks/task-2.md",".agents/artifacts/plans/2026-10-09-issue-337-attempt-identity-migration.tasks/task-3.md",".agents/artifacts/plans/2026-10-09-issue-337-attempt-identity-migration.tasks/task-4.md",".agents/artifacts/plans/2026-10-09-issue-337-attempt-identity-migration.tasks/task-5.md",".agents/artifacts/plans/2026-10-09-issue-337-attempt-identity-migration.tasks/task-6.md",".agents/artifacts/plans/2026-10-09-issue-337-attempt-identity-migration.tasks/task-7.md",".agents/artifacts/plans/2026-10-09-issue-337-attempt-identity-migration.tasks/task-8.md"]},"tasks":[1,2,3,4,5,6,7,8]}],"delivery_base":"907dba234933e1457c2883530bf5f1b83e07a0ec","derived_from":null,"kind":"review-feasibility-delivery","process_records":[{"bounds":[{"added_lines":375,"boundary":"attempt-identity","deleted_lines":0,"record_bytes":47630,"support":{"covers":["p1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p1","last_task":8,"owner":0,"path":".agents/artifacts/specs/2026-10-09-issue-337-attempt-identity-migration-design.md"},{"bounds":[{"added_lines":124,"boundary":"attempt-identity","deleted_lines":0,"record_bytes":18998,"support":{"covers":["p2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p2","last_task":8,"owner":0,"path":".agents/artifacts/plans/2026-10-09-issue-337-attempt-identity-migration.md"},{"bounds":[{"added_lines":56,"boundary":"attempt-identity","deleted_lines":0,"record_bytes":2879,"support":{"covers":["p3"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p3","last_task":8,"owner":0,"path":".agents/artifacts/plans/2026-10-09-issue-337-attempt-identity-migration.tasks/task-1.md"},{"bounds":[{"added_lines":60,"boundary":"attempt-identity","deleted_lines":0,"record_bytes":3497,"support":{"covers":["p4"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p4","last_task":8,"owner":0,"path":".agents/artifacts/plans/2026-10-09-issue-337-attempt-identity-migration.tasks/task-2.md"},{"bounds":[{"added_lines":54,"boundary":"attempt-identity","deleted_lines":0,"record_bytes":2699,"support":{"covers":["p5"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p5","last_task":8,"owner":0,"path":".agents/artifacts/plans/2026-10-09-issue-337-attempt-identity-migration.tasks/task-3.md"},{"bounds":[{"added_lines":54,"boundary":"attempt-identity","deleted_lines":0,"record_bytes":2585,"support":{"covers":["p6"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p6","last_task":8,"owner":0,"path":".agents/artifacts/plans/2026-10-09-issue-337-attempt-identity-migration.tasks/task-4.md"},{"bounds":[{"added_lines":58,"boundary":"attempt-identity","deleted_lines":0,"record_bytes":6952,"support":{"covers":["p7"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p7","last_task":8,"owner":0,"path":".agents/artifacts/plans/2026-10-09-issue-337-attempt-identity-migration.tasks/task-5.md"},{"bounds":[{"added_lines":233,"boundary":"attempt-identity","deleted_lines":0,"record_bytes":18836,"support":{"covers":["p8"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p8","last_task":8,"owner":0,"path":".agents/artifacts/plans/2026-10-09-issue-337-attempt-identity-migration.tasks/task-6.md"},{"bounds":[{"added_lines":173,"boundary":"attempt-identity","deleted_lines":0,"record_bytes":10856,"support":{"covers":["p9"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p9","last_task":8,"owner":0,"path":".agents/artifacts/plans/2026-10-09-issue-337-attempt-identity-migration.tasks/task-7.md"},{"bounds":[{"added_lines":176,"boundary":"attempt-identity","deleted_lines":0,"record_bytes":18041,"support":{"covers":["p10"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p10","last_task":8,"owner":0,"path":".agents/artifacts/plans/2026-10-09-issue-337-attempt-identity-migration.tasks/task-8.md"}],"proposed_boundary":"attempt-identity","schema_version":3}
```

## Standards review provenance

- Plan review: `Codex`, isolated read-only, no fallback, base `eca16cd8`: 6 accepted (4 Blocking, 2 Should fix), 0 rejected, 0 deferred; non-obvious ones are D23–D26.
- Amendment review (`67e64f77`): `Codex`, isolated read-only, focus Tasks 4–8: 2 accepted (1 Blocking, D31; 1 Should fix, direct), 0 rejected, 0 deferred.

---
