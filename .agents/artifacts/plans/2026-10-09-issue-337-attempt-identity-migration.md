# Attempt Run Identity on the Transaction Core Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** every attempt run gets exactly one identity, a core `rel_` UUIDv7 run transaction, and every legacy ledger in one of the four legacy dialects migrates to schema 8 by a dry-run-first, adjacent, atomic, idempotent step that keeps its legacy handle working for live owners.

**Architecture:** a pure module `agent_tools.attempt_identity` holds the dialect grammar, creation keys, the `attempt-run/v1` subject, the 7 → 8 plan and the migration report, and the core gains a read-only `TransactionStore.lookup`. A second package module, `agent_tools.attempt_store`, holds the store effects: the store root `.superpowers/attempt-transactions/`, a blocking mint lock, minting and lookup, the binding check, the bind transform a locked read runs, the read-only check of unlocked reads, the direct index probe, and `migrate`'s rows and report (D27). `workflow-state` keeps each ledger's `state.lock`, the ledger read and commit, the delivery chain and `validate_state`, and is a thin caller for `init-run --creation-key`, `direct-owner` and `migrate`. Installed `workflow-state` runs under the agent_tools interpreter so it can import the core, and `launch-scope` accepts a `rel_` handle (D18).

**Tech stack:** Python 3 standard library and `unittest`; `agent_tools` (`transaction_core`, `transaction_storage`); Nix (`lib/agent-tools.nix`, home-manager); `just`.

Spec: `.agents/artifacts/specs/2026-10-09-issue-337-attempt-identity-migration-design.md`. Its `## Decision ledger` rows D1–D30 are cited by ID. D15–D22 were appended by this plan, D23–D26 by its plan review, and D27–D30 by the review-package amendment.

## Global Constraints

- Base: `eca16cd85453dd290a9ab8ac66b8b3f2f7e697d7` (`origin/main` at planning). The old-helper test pins this exact commit (D13).
- **Never touch a live ledger.** `/Users/anis/tmp/nix-config/.superpowers/` holds the ledgers of the orchestration that runs this plan. No test, command or manual check may run `workflow-state migrate --apply`, a lifecycle write, or any built `workflow-state` against it, or against any `--repo-root` other than a `tempfile` directory. Every test builds its ledgers under `tempfile.TemporaryDirectory()`.
- Subject, key and report literals: subject schema `attempt-run/v1`; report schema `attempt-migration-report/v1`; authority class `attempt-run`; concurrency keys `["attempt-run:" + <creation key>]`; empty proof `{"units": [], "obligations": [], "collectors": {}}`; empty recovery `{"effects": {}, "units": []}`; creation keys `attempt-run/v1:direct:<issue>:<sequence>`, `attempt-run/v1:legacy:<run_id>`, `attempt-run/v1:run:<caller key>`, with caller key `^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$`.
- Closed refusal reasons: `unknown_schema`, `invalid_state`, `unknown_dialect`, `ambiguous_lineage`, `location_mismatch`. Verdicts: `current`, `migrate`, `migrated`, `refused`.
- Store root `<repo root>/.superpowers/attempt-transactions/`, holding a `*` `.gitignore`. Mint lock `<store root>/attempt-runs.lock`, a blocking exclusive `flock` that wraps every `create`. Lock order, outermost first: `.direct-<issue>.lock` → ledger `state.lock`s → mint lock → core locks. No `state.lock` is taken while the mint lock is held (D9).
- New helper code follows `docs/standards/agent-helpers.md`: no `sys.path` edits, and no new path loading; `workflow-state` output keeps its existing `print_json` rendering (sorted keys, compact). `workflow-state.py` imports `agent_tools.attempt_identity` and `agent_tools.attempt_store` with a plain `import` (D11, D27).
- Prose that a task writes into code or docs must describe the code as it is at that task's head. Where a task gives content points rather than text, the implementer writes the sentences from the implemented code.
- Every long command, each test command included, runs in the foreground as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>` from the worktree root, with an explicit timeout above its duration. Commits go through `launch-commit … -- <git commit args>`, signed, with the session's trailers. Scratch files live under `launch-scope scratch`'s root.
- Python tests run as `PYTHONPATH="$PWD/python" python3 -m unittest <file> [-k <pattern>]`, with a timeout of at least 900 s.
- Tasks 1–3 are complete (`1701032a`, `aae76ba8`, `b5519a4b`, each review-clean) and are not re-run; execution resumes at Task 4.
- Tasks 2 and 3 changed the ledger contract that the existing lifecycle suites encode. Those suites (`test_workflow_state.py` except the harness, `test_delivery_workflow.py`, `test_host_admission.py`, `test_delivered_control.py`, `test_admission_replay.py`, `tests/test_launch_scope.py`, `tests/test_launch_commit.py`) are red from Task 2 until Task 5's sweep turns them green. Task 4 must leave their failing set unchanged.
- Review-package budget (D29): `git diff -U10 eca16cd85453dd290a9ab8ac66b8b3f2f7e697d7..HEAD -- <file> | wc -c` stays at most 55000 for `home/common/agent-skills/scripts/workflow-state.py` after Task 4 and at most 60000 for it and for every other changed code or test file after every later task; the cumulative `review-package` check at each task head reports `complete`.
- No task raises an instruction ceiling or edits `instruction-load.json` (D22).
- Final gate, run once on the final head by Task 8: `just build` (timeout 3600 s), `just agent-workflow-tests` (timeout 3600 s) and `just agent-installed-skill-tests` (timeout 3600 s). Task 8 also runs `just agent-instruction-budget` with no `--raise-label`. No agent applies the `instruction-budget-raise` label.

## Test seams

- The workflow-state CLI driven from source through `LifecycleHarness.run_cli`. Its stdout, ledger bytes and `.superpowers` tree are the observable behaviour. The migration fixtures live in the new `home/common/agent-skills/tests/test_attempt_migration.py`.
- `agent_tools.attempt_identity`'s pure functions and `TransactionStore.lookup`, imported normally by the new `tests/test_attempt_identity.py`. `agent_tools.attempt_store` is tested only through the CLI seam above (D27).
- The installed layout: `tests/test_agent_tools_launchers.py` over the built home-manager files (Task 8 only).
- A "tree snapshot" is `{relative path: bytes or "<dir>"}` for every path under `<root>/.superpowers`.

## Delivery estimate and boundaries

Measured at `b5519a4b` (Tasks 1–3 done): `review-package` over `eca16cd8..b5519a4b` returns `decompose_required` on `member_bytes`, with 6 files, a 75006-byte largest member, and 283577 bytes in total. Every changed file's `git diff -U10` is one record, capped at 65536 bytes. `workflow-state.py` alone is 74942 bytes. Most of that is context: about 85 changed regions merge into 33 `-U10` hunks, each carrying about twenty unchanged lines. No issue split helps, since any slice holding Tasks 2 and 3 is over the cap. So Task 4 restructures before more work lands (D27, D28). A scratch replay of Task 4's moves on the current file measured 54618 bytes (an estimate: the replay neither trimmed docstrings nor used the real module name). What remains is the call-site churn D15, D17, D20 and D23 require, which is why the ceiling is 55000 and not the 45000 first targeted (D29). Task 6 adds a thin `command_migrate` and a parser entry, about 3500 bytes (estimate), under the 60000 ceiling.

Other files (estimates): `test_attempt_migration.py`, about 45000 bytes at Task 7; `attempt_store.py`, about 15000; the Task 5 sweep, whose largest file, `test_workflow_state.py`, must stay under 60000 through shared-helper edits. The plan and spec diffs are about 175000. The projected aggregate is about 400000 of the 524288 limit, in at most 8 members. If a ceiling still fails after its task's remedy, the independently deliverable slices are Tasks 1–5 (identity, schema 8, minting, store module and sweep) and Tasks 6–8 (`migrate`, compatibility proofs, installed layout and docs).

## Task index

Task 1 — Core `lookup` and the pure `attempt_identity` module (complete, `1701032a`) — `python/agent_tools/transaction_core.py`, `python/agent_tools/attempt_identity.py`, `tests/test_transaction_core.py`, `tests/test_attempt_identity.py`, `justfile` — full — [task-1.md](2026-10-09-issue-337-attempt-identity-migration.tasks/task-1.md)
Task 2 — Ledger schema 8: bind on locked reads, check on unlocked reads, `init-run` minting, identity-based direct reservation (complete, `aae76ba8`) — `home/common/agent-skills/scripts/workflow-state.py`, `home/common/agent-skills/scripts/workflow_delivery.py`, `home/common/agent-skills/tests/test_workflow_state.py` (harness only), `home/common/agent-skills/tests/test_delivered_control.py` (harness only), `home/common/agent-skills/tests/test_attempt_migration.py`, `python/agent_tools/launch_scope.py`, `tests/test_launch_scope.py` (one new test), `justfile` — full — [task-2.md](2026-10-09-issue-337-attempt-identity-migration.tasks/task-2.md)
Task 3 — `direct-owner` on run transactions (complete, `b5519a4b`) — `home/common/agent-skills/scripts/workflow-state.py`, `home/common/agent-skills/tests/test_workflow_state.py` (harness only), `home/common/agent-skills/tests/test_attempt_migration.py` — full — [task-3.md](2026-10-09-issue-337-attempt-identity-migration.tasks/task-3.md)
Task 4 — Move the attempt store into `agent_tools.attempt_store`, no behaviour change, `workflow-state.py` diff at most 55000 bytes — `python/agent_tools/attempt_store.py`, `home/common/agent-skills/scripts/workflow-state.py`, `python/agent_tools/attempt_identity.py` (docstring) — full — [task-4.md](2026-10-09-issue-337-attempt-identity-migration.tasks/task-4.md)
Task 5 — Regression floor: the existing suites on minted and legacy-dialect runs — `home/common/agent-skills/tests/test_workflow_state.py`, `home/common/agent-skills/tests/test_delivery_workflow.py`, `home/common/agent-skills/tests/test_host_admission.py`, `home/common/agent-skills/tests/test_delivered_control.py`, `home/common/agent-skills/tests/test_admission_replay.py`, `tests/test_launch_scope.py`, `tests/test_launch_commit.py` — full — [task-5.md](2026-10-09-issue-337-attempt-identity-migration.tasks/task-5.md)
Task 6 — `workflow-state migrate`: dry run, apply and report, with the logic in `attempt_store` — `python/agent_tools/attempt_store.py`, `home/common/agent-skills/scripts/workflow-state.py`, `home/common/agent-skills/tests/test_attempt_migration.py` — full — [task-6.md](2026-10-09-issue-337-attempt-identity-migration.tasks/task-6.md)
Task 7 — Live legacy owner and old-helper refusal — `home/common/agent-skills/tests/test_attempt_migration.py` — full — [task-7.md](2026-10-09-issue-337-attempt-identity-migration.tasks/task-7.md)
Task 8 — Installed `workflow-state`, skill text, READMEs and the final gate — `lib/agent-tools.nix`, `home/common/agent-skills/default.nix`, `tests/test_agent_tools_launchers.py`, `home/common/claude-code/skills/orchestrate-issues/SKILL.md`, `home/common/agent-skills/skills/from-issue/acquire-durable.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `python/README.md`, `home/common/agent-skills/README.md` — full — [task-8.md](2026-10-09-issue-337-attempt-identity-migration.tasks/task-8.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 6 | `test_attempt_migration.py`: `MigrationAcceptanceTest.test_ac1_minted_runs_and_legacy_rows_with_lineage`, which builds on Task 2's `InitRunMintTest` and Task 3's `DirectOwnerIdentityTest`, run by `just agent-workflow-tests` |
| AC2 | code | Task 6 | `test_attempt_migration.py`: `MigrationAcceptanceTest.test_ac2_identity_never_comes_from_names` |
| AC3 | code | Task 6 | `test_attempt_migration.py`: `MigrationAcceptanceTest.test_ac3_dry_run_then_idempotent_apply`, `test_ac3_refusals_are_byte_identical`, `test_ac3_precreated_transaction_is_bound`, `test_ac3_held_mint_lock_makes_apply_wait` |
| AC4 | code | Task 7 | `test_attempt_migration.py`: `LegacyOwnerCompatibilityTest.test_control_migrates_under_a_live_owner`, `test_owner_write_is_the_migrating_write`, `test_base_helper_refuses_schema_8_without_writing` |
| AC5 | code | Task 8 | `just agent-workflow-tests` green at the final head with Task 5's sweep as the only change to pre-existing tests, `test_admission_replay` on its committed baseline; `just build` |

## Decisions

- Identity record, subject, alias index and lookup: D1, D2, D6. Lineage from recorded fields only: D3. Legacy handle kept: D4. Launch references through the action-id parser: D5.
- One package module plus the thin shell in workflow-state: D7. Exit codes and refusals as data: D8. Blocking mint lock: D9. No reverse transform: D10. Installed interpreter: D11, with `-I` settled by D16.
- `init-run --run-id` re-bootstraps only, and the test run-id sweep is the floor's one declared change: D12. Old-helper test from the pinned commit: D13. Bind on every locked read and commit what was bound: D14.
- Direct reservation from identity: D15. Direct-owner mints at handle computation and passes the issue explicitly: D17. `rel_` handles in launch-scope: D18. The sweep's declared change: D19. `RunIdentity` threading and empty migration contracts: D20. Fixture shapes: D21. Instruction ceilings unchanged: D22. D15–D22 were appended by this plan.
- Plan-review dispositions: direct-owner preflights every retained ledger before binding any: D23. Migration fixtures on `LifecycleHarness` with the #220 driver in its own root: D24. Harness `finish` keeps schema-8 ledgers at schema 8: D25. The base-helper test's positive control and schema diagnostic: D26.
- Review-package amendment: the store effects and `migrate`'s logic move to `agent_tools.attempt_store`, which partly reverses D7: D27. The store's location comes from the ledger path: D28. The per-file `-U10` ceilings: D29. The original Tasks 7 and 8 merge into Task 8, and Tasks 4–6 become 5–7: D30.

## Standards review provenance

- Reviewer: `Codex`, isolated read-only mode, no focus, no fallback.
- Base: `eca16cd85453dd290a9ab8ac66b8b3f2f7e697d7`.
- Findings: 6 accepted (4 Blocking, 2 Should fix), 0 rejected, 0 deferred. Non-obvious ones are D23–D26; the Task 1 predecessor test and the Task 8 phrase pin were direct fixes.

---
